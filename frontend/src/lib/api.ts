const API_BASE_URL = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000/api/v1';

class ApiClient {
  private getHeaders(extraHeaders: Record<string, string> = {}): HeadersInit {
    const headers: Record<string, string> = {
      'Content-Type': 'application/json',
      ...extraHeaders,
    };

    if (typeof window !== 'undefined') {
      const token = localStorage.getItem('shoppilot_access_token');
      if (token) {
        headers['Authorization'] = `Bearer ${token}`;
      }
      const activeStoreId = localStorage.getItem('shoppilot_active_store_id');
      if (activeStoreId) {
        headers['x-store-id'] = activeStoreId;
      }
    }
    return headers;
  }

  private isRefreshing = false;
  private refreshSubscribers: ((token: string) => void)[] = [];

  private onTokenRefreshed(token: string) {
    this.refreshSubscribers.forEach((cb) => cb(token));
    this.refreshSubscribers = [];
  }

  private addRefreshSubscriber(cb: (token: string) => void) {
    this.refreshSubscribers.push(cb);
  }

  async request<T>(endpoint: string, options: RequestInit = {}): Promise<T> {
    const url = `${API_BASE_URL}${endpoint.startsWith('/') ? endpoint : `/${endpoint}`}`;
    const headers = this.getHeaders(options.headers as Record<string, string>);

    let response = await fetch(url, {
      ...options,
      headers,
    });

    if (
      response.status === 401 &&
      typeof window !== 'undefined' &&
      !endpoint.includes('/auth/login/') &&
      !endpoint.includes('/auth/token/refresh/')
    ) {
      const refreshToken = localStorage.getItem('shoppilot_refresh_token');
      if (refreshToken) {
        if (!this.isRefreshing) {
          this.isRefreshing = true;
          try {
            const refreshRes = await fetch(`${API_BASE_URL}/auth/token/refresh/`, {
              method: 'POST',
              headers: { 'Content-Type': 'application/json' },
              body: JSON.stringify({ refresh: refreshToken }),
            });

            if (refreshRes.ok) {
              const refreshData = await refreshRes.json();
              const newAccess = refreshData.access;
              localStorage.setItem('shoppilot_access_token', newAccess);
              this.isRefreshing = false;
              this.onTokenRefreshed(newAccess);

              // Retry original request with new access token
              const newHeaders = this.getHeaders(options.headers as Record<string, string>);
              response = await fetch(url, {
                ...options,
                headers: newHeaders,
              });
            } else {
              this.isRefreshing = false;
              localStorage.removeItem('shoppilot_access_token');
              localStorage.removeItem('shoppilot_refresh_token');
            }
          } catch {
            this.isRefreshing = false;
          }
        } else {
          return new Promise<T>((resolve, reject) => {
            this.addRefreshSubscriber(async () => {
              try {
                const newHeaders = this.getHeaders(options.headers as Record<string, string>);
                const retryRes = await fetch(url, { ...options, headers: newHeaders });
                if (!retryRes.ok) {
                  const errorData = await retryRes.json().catch(() => ({}));
                  reject(new Error(errorData.error || errorData.detail || `Error ${retryRes.status}`));
                } else {
                  resolve(await retryRes.json());
                }
              } catch (e) {
                reject(e);
              }
            });
          });
        }
      }
    }

    if (!response.ok) {
      let errorMsg = `Error ${response.status}: ${response.statusText}`;
      try {
        const errorData = await response.json();
        errorMsg = errorData.error || errorData.detail || JSON.stringify(errorData);
      } catch {}
      throw new Error(errorMsg);
    }

    return response.json();
  }

  async downloadFile(endpoint: string, filename: string): Promise<void> {
    const url = `${API_BASE_URL}${endpoint.startsWith('/') ? endpoint : `/${endpoint}`}`;
    const headers = this.getHeaders();
    const res = await fetch(url, { headers });
    if (!res.ok) {
      throw new Error(`Failed to download file: ${res.statusText}`);
    }
    const blob = await res.blob();
    const downloadUrl = window.URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = downloadUrl;
    a.download = filename;
    document.body.appendChild(a);
    a.click();
    a.remove();
    window.URL.revokeObjectURL(downloadUrl);
  }

  // Auth
  async login(credentials: { email?: string; phone_number?: string; password: string }) {
    return this.request<{ user: any; access: string; refresh: string }>('/auth/login/', {
      method: 'POST',
      body: JSON.stringify(credentials),
    });
  }

  async register(data: { email?: string; phone_number?: string; full_name: string; password: string; business_name?: string }) {
    return this.request<{ user: any; access: string; refresh: string }>('/auth/register/', {
      method: 'POST',
      body: JSON.stringify(data),
    });
  }

  async getMe() {
    return this.request<any>('/auth/me/');
  }

  // Tenancy
  async getStores() {
    return this.request<{ results: any[] } | any[]>('/tenancy/stores/');
  }

  async createStore(data: { name: string; currency?: string }) {
    return this.request<any>('/tenancy/stores/', {
      method: 'POST',
      body: JSON.stringify(data),
    });
  }

  // Analytics
  async getOverviewMetrics(days: number = 30) {
    return this.request<any>(`/analytics/overview/?days=${days}`);
  }

  // Daily Action Center
  async getDailyActions() {
    return this.request<{ results: any[] } | any[]>('/daily-actions/');
  }

  async updateDailyActionStatus(id: string, status: string, note?: string) {
    return this.request<any>(`/daily-actions/${id}/update-status/`, {
      method: 'POST',
      body: JSON.stringify({ status, resolution_note: note || '' }),
    });
  }

  // Catalog
  async getProducts(params?: { search?: string; status?: string; category?: string }) {
    const q = new URLSearchParams();
    if (params?.search) q.append('search', params.search);
    if (params?.status) q.append('status', params.status);
    if (params?.category) q.append('category', params.category);
    return this.request<{ results: any[] } | any[]>(`/catalog/products/?${q.toString()}`);
  }

  async getCategories() {
    return this.request<{ results: any[] } | any[]>('/catalog/categories/');
  }

  async createProduct(data: any) {
    return this.request<any>('/catalog/products/', {
      method: 'POST',
      body: JSON.stringify(data),
    });
  }

  // Inventory
  async getInventoryBalances(params?: { low_stock?: boolean; warehouse?: string; search?: string }) {
    const q = new URLSearchParams();
    if (params?.low_stock) q.append('low_stock', 'true');
    if (params?.warehouse) q.append('warehouse', params.warehouse);
    if (params?.search) q.append('search', params.search);
    return this.request<{ results: any[] } | any[]>(`/inventory/balances/?${q.toString()}`);
  }

  async getWarehouses() {
    return this.request<{ results: any[] } | any[]>('/inventory/warehouses/');
  }

  async adjustStock(data: { warehouse_id: string; variant_id: string; new_on_hand: number; reason?: string }) {
    return this.request<any>('/inventory/adjustments/', {
      method: 'POST',
      body: JSON.stringify(data),
    });
  }

  async transferStock(data: {
    source_warehouse_id: string;
    dest_warehouse_id: string;
    variant_id: string;
    quantity: number;
    reason?: string;
  }) {
    return this.request<any>('/inventory/transfers/', {
      method: 'POST',
      body: JSON.stringify(data),
    });
  }

  async getReorderSuggestions() {
    return this.request<any[]>('/inventory/reorder-suggestions/');
  }

  // Orders
  async getOrders(params?: { order_status?: string; payment_status?: string; channel?: string; search?: string }) {
    const q = new URLSearchParams();
    if (params?.order_status) q.append('order_status', params.order_status);
    if (params?.payment_status) q.append('payment_status', params.payment_status);
    if (params?.channel) q.append('channel', params.channel);
    if (params?.search) q.append('search', params.search);
    return this.request<{ results: any[] } | any[]>(`/orders/?${q.toString()}`);
  }

  async getOrder(id: string) {
    return this.request<any>(`/orders/${id}/`);
  }

  async createOrder(data: any) {
    return this.request<any>('/orders/', {
      method: 'POST',
      body: JSON.stringify(data),
    });
  }

  async cancelOrder(id: string, reason?: string) {
    return this.request<any>(`/orders/${id}/cancel/`, {
      method: 'POST',
      body: JSON.stringify({ reason: reason || '' }),
    });
  }

  async fulfillOrder(id: string, data?: { tracking_number?: string; shipping_cost?: number }) {
    return this.request<any>(`/orders/${id}/fulfill/`, {
      method: 'POST',
      body: JSON.stringify(data || {}),
    });
  }

  async importOrdersCsv(file: File) {
    const formData = new FormData();
    formData.append('file', file);

    const headers: Record<string, string> = {};
    if (typeof window !== 'undefined') {
      const token = localStorage.getItem('shoppilot_access_token');
      if (token) headers['Authorization'] = `Bearer ${token}`;
      const activeStoreId = localStorage.getItem('shoppilot_active_store_id');
      if (activeStoreId) headers['x-store-id'] = activeStoreId;
    }

    const response = await fetch(`${API_BASE_URL}/orders/import-csv/`, {
      method: 'POST',
      headers,
      body: formData,
    });
    if (!response.ok) {
      throw new Error(`Import failed with status ${response.status}`);
    }
    return response.json();
  }

  // Payments
  async getPayments(params?: { status?: string; method?: string }) {
    const q = new URLSearchParams();
    if (params?.status) q.append('status', params.status);
    if (params?.method) q.append('method', params.method);
    return this.request<{ results: any[] } | any[]>(`/payments/?${q.toString()}`);
  }

  async verifyPayment(id: string) {
    return this.request<any>(`/payments/${id}/verify/`, {
      method: 'POST',
    });
  }

  async rejectPayment(id: string, reason: string) {
    return this.request<any>(`/payments/${id}/reject/`, {
      method: 'POST',
      body: JSON.stringify({ reason }),
    });
  }

  // Fulfillment
  async getShipments() {
    return this.request<{ results: any[] } | any[]>('/fulfillment/');
  }

  async getPackingSlip(shipmentId: string) {
    return this.request<any>(`/fulfillment/${shipmentId}/packing-slip/`);
  }

  // Team Management & RBAC
  async getTeamMembers() {
    return this.request<{ results: any[] } | any[]>('/tenancy/memberships/');
  }

  async suspendTeamMember(id: string) {
    return this.request<any>(`/tenancy/memberships/${id}/suspend/`, {
      method: 'POST',
    });
  }

  async reactivateTeamMember(id: string) {
    return this.request<any>(`/tenancy/memberships/${id}/reactivate/`, {
      method: 'POST',
    });
  }

  async getTeamInvitations() {
    return this.request<{ results: any[] } | any[]>('/tenancy/invitations/');
  }

  async sendTeamInvitation(data: { email: string; role: string; custom_permissions?: string[] }) {
    return this.request<any>('/tenancy/invitations/', {
      method: 'POST',
      body: JSON.stringify(data),
    });
  }

  async revokeTeamInvitation(id: string) {
    return this.request<any>(`/tenancy/invitations/${id}/revoke/`, {
      method: 'POST',
    });
  }

  async acceptTeamInvitation(token: string) {
    return this.request<any>('/tenancy/invitations/accept/', {
      method: 'POST',
      body: JSON.stringify({ token }),
    });
  }

  // Tasks Management
  async getTaskCategories() {
    return this.request<{ results: any[] } | any[]>('/tasks/categories/');
  }

  async createTaskCategory(data: { name: string; color?: string; icon?: string }) {
    return this.request<any>('/tasks/categories/', {
      method: 'POST',
      body: JSON.stringify(data),
    });
  }

  async getTasks(params?: {
    status?: string;
    priority?: string;
    category?: string;
    assignee?: string;
    my_tasks?: boolean;
    overdue?: boolean;
  }) {
    const q = new URLSearchParams();
    if (params?.status) q.append('status', params.status);
    if (params?.priority) q.append('priority', params.priority);
    if (params?.category) q.append('category', params.category);
    if (params?.assignee) q.append('assignee', params.assignee);
    if (params?.my_tasks) q.append('my_tasks', 'true');
    if (params?.overdue) q.append('overdue', 'true');
    return this.request<{ results: any[] } | any[]>(`/tasks/tasks/?${q.toString()}`);
  }

  async getTaskDetail(id: string) {
    return this.request<any>(`/tasks/tasks/${id}/`);
  }

  async createTask(data: any) {
    return this.request<any>('/tasks/tasks/', {
      method: 'POST',
      body: JSON.stringify(data),
    });
  }

  async updateTaskStatus(id: string, status: string, completion_evidence?: string) {
    return this.request<any>(`/tasks/tasks/${id}/status/`, {
      method: 'POST',
      body: JSON.stringify({ status, completion_evidence: completion_evidence || '' }),
    });
  }

  async verifyTask(id: string, approved: boolean, feedback?: string) {
    return this.request<any>(`/tasks/tasks/${id}/verify/`, {
      method: 'POST',
      body: JSON.stringify({ approved, feedback: feedback || '' }),
    });
  }

  async addTaskComment(id: string, content: string) {
    return this.request<any>(`/tasks/tasks/${id}/comments/`, {
      method: 'POST',
      body: JSON.stringify({ content }),
    });
  }

  async addTaskChecklistItem(id: string, title: string) {
    return this.request<any>(`/tasks/tasks/${id}/checklist/`, {
      method: 'POST',
      body: JSON.stringify({ title }),
    });
  }

  async toggleTaskChecklistItem(taskId: string, itemId: string) {
    return this.request<any>(`/tasks/tasks/${taskId}/checklist/${itemId}/toggle/`, {
      method: 'POST',
    });
  }

  async getTaskSummary() {
    return this.request<{
      total: number;
      todo: number;
      in_progress: number;
      in_review: number;
      completed: number;
      overdue: number;
      my_tasks: number;
    }>('/tasks/tasks/summary/');
  }

  // Social Media Operations & Planner
  async getSocialAccounts() {
    return this.request<{ results: any[] } | any[]>('/social/accounts/');
  }

  async createSocialAccount(data: any) {
    return this.request<any>('/social/accounts/', {
      method: 'POST',
      body: JSON.stringify(data),
    });
  }

  async getSocialCampaigns() {
    return this.request<{ results: any[] } | any[]>('/social/campaigns/');
  }

  async createSocialCampaign(data: any) {
    return this.request<any>('/social/campaigns/', {
      method: 'POST',
      body: JSON.stringify(data),
    });
  }

  async getSocialContent(params?: {
    status?: string;
    content_type?: string;
    account?: string;
    campaign?: string;
    start_date?: string;
    end_date?: string;
  }) {
    const q = new URLSearchParams();
    if (params?.status) q.append('status', params.status);
    if (params?.content_type) q.append('content_type', params.content_type);
    if (params?.account) q.append('account', params.account);
    if (params?.campaign) q.append('campaign', params.campaign);
    if (params?.start_date) q.append('start_date', params.start_date);
    if (params?.end_date) q.append('end_date', params.end_date);
    return this.request<{ results: any[] } | any[]>(`/social/content/?${q.toString()}`);
  }

  async getSocialContentDetail(id: string) {
    return this.request<any>(`/social/content/${id}/`);
  }

  async createSocialContent(data: any) {
    return this.request<any>('/social/content/', {
      method: 'POST',
      body: JSON.stringify(data),
    });
  }

  async submitContentForReview(id: string) {
    return this.request<any>(`/social/content/${id}/submit-review/`, {
      method: 'POST',
    });
  }

  async reviewContent(id: string, action: string, feedback?: string) {
    return this.request<any>(`/social/content/${id}/review/`, {
      method: 'POST',
      body: JSON.stringify({ action, feedback: feedback || '' }),
    });
  }

  async scheduleContent(id: string, scheduled_at: string) {
    return this.request<any>(`/social/content/${id}/schedule/`, {
      method: 'POST',
      body: JSON.stringify({ scheduled_at }),
    });
  }

  async publishContent(id: string, published_url?: string) {
    return this.request<any>(`/social/content/${id}/publish/`, {
      method: 'POST',
      body: JSON.stringify({ published_url: published_url || '' }),
    });
  }

  async recordContentMetrics(id: string, data: any) {
    return this.request<any>(`/social/content/${id}/metrics/`, {
      method: 'POST',
      body: JSON.stringify(data),
    });
  }

  async getSocialAnalyticsSummary(days: number = 30) {
    return this.request<any>(`/social/analytics/summary/?days=${days}`);
  }

  // Feature Entitlements & Modularity
  async getFeatureCatalog() {
    return this.request<{
      tier: string;
      tier_display: string;
      features: Array<{
        key: string;
        name_fa: string;
        description_fa: string;
        category: string;
        is_core: boolean;
        is_entitled: boolean;
        is_active: boolean;
        min_tier: string;
        depends_on: string[];
        missing_dependencies: string[];
        dependents: string[];
        integrations: string[];
        impact_warning_fa: string;
      }>;
    }>('/features/catalog/');
  }

  async toggleFeature(feature: string, enabled: boolean) {
    return this.request<{
      feature: string;
      is_active: boolean;
      action: string;
      message: string;
      active_dependents_affected: string[];
    }>('/features/toggle/', {
      method: 'POST',
      body: JSON.stringify({ feature, enabled }),
    });
  }

  async updateSubscriptionTier(tier: string) {
    return this.request<{
      tier: string;
      tier_display: string;
      message: string;
    }>('/features/tier/', {
      method: 'POST',
      body: JSON.stringify({ tier }),
    });
  }

  async getIntegrations() {
    return this.request<Record<string, {
      name: string;
      display_name_fa: string;
      description_fa: string;
      status: string;
      is_ready: boolean;
      message: string;
    }>>('/features/integrations/');
  }

  async getCanonicalIntegrations() {
    return this.request<Array<{
      id: string;
      name: string;
      category: string;
      display_name_fa: string;
      description_fa: string;
      guide_fa: string;
      status: string;
      is_active: boolean;
      is_ready: boolean;
      message: string;
      last_tested_at?: string;
      last_connected_at?: string;
      last_test_error?: string;
      last_test_success?: boolean;
      schema: Array<{
        name: string;
        label_fa: string;
        type: 'text' | 'password' | 'number' | 'boolean' | 'select' | 'url';
        required: boolean;
        is_secret: boolean;
        help_text_fa?: string;
        placeholder?: string;
        default?: any;
        options?: Array<{ value: string; label: string }>;
      }>;
      config: Record<string, any>;
    }>>('/features/integrations/?canonical=true');
  }

  async getIntegrationDetail(name: string) {
    return this.request<any>(`/features/integrations/${name}/`);
  }

  async saveIntegrationConfig(name: string, config: Record<string, any>) {
    return this.request<{
      success: boolean;
      message: string;
      status: string;
      is_active: boolean;
      config: Record<string, any>;
    }>(`/features/integrations/${name}/save/`, {
      method: 'POST',
      body: JSON.stringify({ config }),
    });
  }

  async testIntegration(name: string) {
    return this.request<{
      success: boolean;
      status: string;
      message: string;
      details?: Record<string, any>;
    }>(`/features/integrations/${name}/test/`, {
      method: 'POST',
    });
  }

  async activateIntegration(name: string) {
    return this.request<{
      success: boolean;
      message: string;
      status: string;
      is_active: boolean;
    }>(`/features/integrations/${name}/activate/`, {
      method: 'POST',
    });
  }

  async deactivateIntegration(name: string) {
    return this.request<{
      success: boolean;
      message: string;
      status: string;
      is_active: boolean;
    }>(`/features/integrations/${name}/deactivate/`, {
      method: 'POST',
    });
  }

  async sendTestSMS(name: string, to: string) {
    return this.request<{
      success: boolean;
      message: string;
      details?: any;
    }>(`/features/integrations/${name}/send-test-sms/`, {
      method: 'POST',
      body: JSON.stringify({ to }),
    });
  }

  async sendTestEmail(name: string, to: string) {
    return this.request<{
      success: boolean;
      message: string;
    }>(`/features/integrations/${name}/send-test-email/`, {
      method: 'POST',
      body: JSON.stringify({ to }),
    });
  }

  async configureIntegration(name: string, state: string, credentials?: Record<string, any>) {
    return this.request<any>('/features/integrations/configure/', {
      method: 'POST',
      body: JSON.stringify({ name, state, credentials: credentials || {} }),
    });
  }


  // Subscription Invoices & Checkout
  async getSubscriptionInvoices() {
    return this.request<any[]>('/features/invoices/');
  }

  async createSubscriptionInvoice(data: { tier: string; billing_cycle?: 'MONTHLY' | 'ANNUAL' }) {
    return this.request<any>('/features/invoices/', {
      method: 'POST',
      body: JSON.stringify(data),
    });
  }

  async checkoutSubscriptionInvoice(invoiceId: string, data?: { callback_url?: string; gateway?: string }) {
    return this.request<{
      success: boolean;
      invoice_id: string;
      authority?: string;
      payment_url?: string;
      amount: string | number;
    }>(`/features/invoices/${invoiceId}/checkout/`, {
      method: 'POST',
      body: JSON.stringify(data || {}),
    });
  }

  async verifySubscriptionInvoice(data: { authority: string; gateway?: string }) {
    return this.request<any>('/features/invoices/verify/', {
      method: 'POST',
      body: JSON.stringify(data),
    });
  }

  async manualApproveSubscriptionInvoice(invoiceId: string, data: { reason: string; tracking_code?: string }) {
    return this.request<any>(`/features/invoices/${invoiceId}/manual-approve/`, {
      method: 'POST',
      body: JSON.stringify(data),
    });
  }

  // Suppliers & Purchase Orders
  async getSuppliers(search?: string) {
    const q = search ? `?search=${encodeURIComponent(search)}` : '';
    return this.request<{ results: any[] } | any[]>(`/suppliers/suppliers/${q}`);
  }

  async createSupplier(data: any) {
    return this.request<any>('/suppliers/suppliers/', {
      method: 'POST',
      body: JSON.stringify(data),
    });
  }

  async getPurchaseOrders(status?: string) {
    const q = status ? `?status=${status}` : '';
    return this.request<{ results: any[] } | any[]>(`/suppliers/purchase-orders/${q}`);
  }

  async createPurchaseOrder(data: any) {
    return this.request<any>('/suppliers/purchase-orders/', {
      method: 'POST',
      body: JSON.stringify(data),
    });
  }

  async approvePurchaseOrder(id: string) {
    return this.request<any>(`/suppliers/purchase-orders/${id}/approve/`, {
      method: 'POST',
    });
  }

  async receivePOGoods(id: string, receipts: Array<{ item_id: string; quantity_received: number }>) {
    return this.request<any>(`/suppliers/purchase-orders/${id}/receive-goods/`, {
      method: 'POST',
      body: JSON.stringify({ receipts }),
    });
  }

  // Customer Returns & RMAs
  async getReturnRequests(status?: string) {
    const q = status ? `?status=${status}` : '';
    return this.request<{ results: any[] } | any[]>(`/returns/requests/${q}`);
  }

  async createReturnRequest(data: any) {
    return this.request<any>('/returns/requests/', {
      method: 'POST',
      body: JSON.stringify(data),
    });
  }

  async approveReturnRequest(id: string, staff_notes?: string) {
    return this.request<any>(`/returns/requests/${id}/approve/`, {
      method: 'POST',
      body: JSON.stringify({ staff_notes: staff_notes || '' }),
    });
  }

  async inspectAndProcessReturn(id: string, data: any) {
    return this.request<any>(`/returns/requests/${id}/inspect-and-process/`, {
      method: 'POST',
      body: JSON.stringify(data),
    });
  }

  // Finance & Operating Expenses
  async getExpenses(category?: string) {
    const q = category ? `?category=${category}` : '';
    return this.request<{ results: any[] } | any[]>(`/finance/expenses/${q}`);
  }

  async createExpense(data: any) {
    return this.request<any>('/finance/expenses/', {
      method: 'POST',
      body: JSON.stringify(data),
    });
  }

  async getFinancialStatement(days: number = 30) {
    return this.request<any>(`/finance/statement/?days=${days}`);
  }

  // CRM & Customer Profiles
  async getCRMProfiles(params?: { segment?: string; search?: string }) {
    const q = new URLSearchParams();
    if (params?.segment) q.append('segment', params.segment);
    if (params?.search) q.append('search', params.search);
    return this.request<{ results: any[] } | any[]>(`/crm/profiles/?${q.toString()}`);
  }

  async recalculateCRM() {
    return this.request<any>('/crm/profiles/recalculate-all/', {
      method: 'POST',
    });
  }

  async getCRMSegmentsSummary() {
    return this.request<any[]>('/crm/profiles/segments-summary/');
  }

  async addCRMInteraction(profileId: string, data: any) {
    return this.request<any>(`/crm/profiles/${profileId}/add-interaction/`, {
      method: 'POST',
      body: JSON.stringify(data),
    });
  }

  // Unified Social Inbox
  async getInboxThreads(params?: { channel?: string; status?: string }) {
    const q = new URLSearchParams();
    if (params?.channel) q.append('channel', params.channel);
    if (params?.status) q.append('status', params.status);
    return this.request<{ results: any[] } | any[]>(`/social-inbox/threads/?${q.toString()}`);
  }

  async sendInboxMessage(threadId: string, text: string, isAi?: boolean, wasEdited?: boolean) {
    return this.request<any>(`/social-inbox/threads/${threadId}/send-message/`, {
      method: 'POST',
      body: JSON.stringify({ text, is_ai_generated: isAi || false, was_edited_by_human: wasEdited || false }),
    });
  }

  async suggestAIReply(threadId: string) {
    return this.request<{ suggested_text: string; source: string }>(`/social-inbox/threads/${threadId}/suggest-ai-reply/`, {
      method: 'POST',
    });
  }

  async resolveInboxThread(threadId: string) {
    return this.request<any>(`/social-inbox/threads/${threadId}/resolve/`, {
      method: 'POST',
    });
  }

  // Marketing & Coupons
  async getCoupons() {
    return this.request<{ results: any[] } | any[]>('/marketing/coupons/');
  }

  async createCoupon(data: any) {
    return this.request<any>('/marketing/coupons/', {
      method: 'POST',
      body: JSON.stringify(data),
    });
  }

  async validateCoupon(code: string, orderAmount: number) {
    return this.request<any>('/marketing/coupons/validate/', {
      method: 'POST',
      body: JSON.stringify({ code, order_amount: orderAmount }),
    });
  }

  async getLoyaltyAccounts() {
    return this.request<{ results: any[] } | any[]>('/marketing/loyalty/');
  }

  // Automation
  async getAutomationRules() {
    return this.request<{ results: any[] } | any[]>('/automation/rules/');
  }

  async createAutomationRule(data: any) {
    return this.request<any>('/automation/rules/', {
      method: 'POST',
      body: JSON.stringify(data),
    });
  }

  async testRunAutomationRule(id: string, payload: any) {
    return this.request<any>(`/automation/rules/${id}/test-run/`, {
      method: 'POST',
      body: JSON.stringify({ payload }),
    });
  }

  // Intelligence
  async getDemandForecasts(days: number = 30) {
    return this.request<any[]>(`/intelligence/forecasts/?days=${days}`);
  }

  async getOrderRisk(orderId: string) {
    return this.request<any>(`/intelligence/order-risk/${orderId}/`);
  }

  async askAICopilot(question: string) {
    return this.request<{ question: string; answer: string; source: string }>('/intelligence/copilot/', {
      method: 'POST',
      body: JSON.stringify({ question }),
    });
  }

  // Fulfillment & Shipping
  async getFulfillmentPackingSlip(shipmentId: string) {
    return this.request<any>(`/fulfillment/shipments/${shipmentId}/packing-slip/`);
  }

  async estimateShippingQuote(params: { weight_grams: number; origin_city: string; dest_city: string; carrier?: string }) {
    const query = new URLSearchParams({
      weight_grams: String(params.weight_grams),
      origin_city: params.origin_city,
      dest_city: params.dest_city,
      carrier: params.carrier || 'IRPOST',
    }).toString();
    return this.request<any>(`/fulfillment/shipments/estimate-quote/?${query}`);
  }

  async updateShipmentStatus(shipmentId: string, data: { status: string; location?: string; description?: string; failed_reason?: string }) {
    return this.request<any>(`/fulfillment/shipments/${shipmentId}/update-status/`, {
      method: 'POST',
      body: JSON.stringify(data),
    });
  }

  // Social & Team Proof
  async submitContentProof(contentId: string, data: { proof_url?: string; proof_image_url?: string }) {
    return this.request<any>(`/social/content/${contentId}/submit-proof/`, {
      method: 'POST',
      body: JSON.stringify(data),
    });
  }

  async verifyContentProof(contentId: string) {
    return this.request<any>(`/social/content/${contentId}/verify-proof/`, {
      method: 'POST',
    });
  }

  async getTeamSocialPerformance(days: number = 30) {
    return this.request<any>(`/social/team-performance/?days=${days}`);
  }

  async linkThreadOrder(threadId: string, orderId: string) {
    return this.request<any>(`/social-inbox/threads/${threadId}/link-order/`, {
      method: 'POST',
      body: JSON.stringify({ order_id: orderId }),
    });
  }

  async updateThreadNotes(threadId: string, notes: string) {
    return this.request<any>(`/social-inbox/threads/${threadId}/update-notes/`, {
      method: 'POST',
      body: JSON.stringify({ notes }),
    });
  }

  // Marketing & Retention
  async getAbandonedCarts(status?: string) {
    const query = status ? `?status=${status}` : '';
    return this.request<any[]>(`/marketing/abandoned-carts/${query}`);
  }

  async recoverAbandonedCart(cartId: string, couponCode?: string) {
    return this.request<any>(`/marketing/abandoned-carts/${cartId}/trigger-recovery/`, {
      method: 'POST',
      body: JSON.stringify({ coupon_code: couponCode }),
    });
  }

  async getReferrals() {
    return this.request<any[]>('/marketing/referrals/');
  }

  async convertReferral(referralId: string) {
    return this.request<any>(`/marketing/referrals/${referralId}/convert/`, {
      method: 'POST',
    });
  }

  async getProductRecommendations(sourceVariantId?: string) {
    const query = sourceVariantId ? `?source_variant_id=${sourceVariantId}` : '';
    return this.request<any[]>(`/marketing/recommendations/${query}`);
  }

  // Finance & Settlements
  async getGatewaySettlements() {
    return this.request<any[]>('/finance/settlements/');
  }

  async createGatewaySettlement(data: any) {
    return this.request<any>('/finance/settlements/', {
      method: 'POST',
      body: JSON.stringify(data),
    });
  }

  async getAccountsPayableReceivable(entityType?: string, status?: string) {
    const params = new URLSearchParams();
    if (entityType) params.append('entity_type', entityType);
    if (status) params.append('status', status);
    const query = params.toString() ? `?${params.toString()}` : '';
    return this.request<any[]>(`/finance/debts-credits/${query}`);
  }

  async getRefundRecords() {
    return this.request<any[]>('/finance/refunds/');
  }

  async createRefundRecord(data: any) {
    return this.request<any>('/finance/refunds/', {
      method: 'POST',
      body: JSON.stringify(data),
    });
  }

  getFinanceExportCSVUrl() {
    return `${API_BASE_URL}/finance/export-csv/`;
  }

  // Business Intelligence
  async getSlowMovers(days: number = 60) {
    return this.request<any>(`/intelligence/slow-movers/?days=${days}`);
  }

  async getCustomerFeedback(params?: { category?: string; sentiment?: string; is_resolved?: boolean }) {
    const searchParams = new URLSearchParams();
    if (params?.category) searchParams.append('category', params.category);
    if (params?.sentiment) searchParams.append('sentiment', params.sentiment);
    if (params?.is_resolved !== undefined) searchParams.append('is_resolved', String(params.is_resolved));
    const query = searchParams.toString() ? `?${searchParams.toString()}` : '';
    return this.request<any[]>(`/intelligence/feedback/${query}`);
  }

  async createCustomerFeedback(data: any) {
    return this.request<any>('/intelligence/feedback/', {
      method: 'POST',
      body: JSON.stringify(data),
    });
  }

  async getCompetitorPrices() {
    return this.request<any[]>('/intelligence/competitor-prices/');
  }

  async createCompetitorPrice(data: any) {
    return this.request<any>('/intelligence/competitor-prices/', {
      method: 'POST',
      body: JSON.stringify(data),
    });
  }

  // Wholesale & POS
  async getB2BClients() {
    return this.request<any[]>('/wholesale-pos/clients/');
  }

  async createB2BClient(data: any) {
    return this.request<any>('/wholesale-pos/clients/', {
      method: 'POST',
      body: JSON.stringify(data),
    });
  }

  async getVolumeTiers(variantId?: string) {
    const query = variantId ? `?variant_id=${variantId}` : '';
    return this.request<any[]>(`/wholesale-pos/volume-tiers/${query}`);
  }

  async createVolumeTier(data: any) {
    return this.request<any>('/wholesale-pos/volume-tiers/', {
      method: 'POST',
      body: JSON.stringify(data),
    });
  }

  async getPOSTerminals() {
    return this.request<any[]>('/wholesale-pos/terminals/');
  }

  async createPOSTerminal(data: any) {
    return this.request<any>('/wholesale-pos/terminals/', {
      method: 'POST',
      body: JSON.stringify(data),
    });
  }

  async getPOSSessions() {
    return this.request<any[]>('/wholesale-pos/sessions/');
  }

  async createPOSSession(data: { terminal: string; opening_cash?: number }) {
    return this.request<any>('/wholesale-pos/sessions/', {
      method: 'POST',
      body: JSON.stringify(data),
    });
  }

  async closePOSSession(sessionId: string, data: { closing_cash: number; notes?: string }) {
    return this.request<any>(`/wholesale-pos/sessions/${sessionId}/close-session/`, {
      method: 'POST',
      body: JSON.stringify(data),
    });
  }

  async posQuickCheckout(data: {
    session_id: string;
    items: { variant_id: string; quantity: number; unit_price?: number }[];
    customer_phone?: string;
    customer_name?: string;
    payment_method?: string;
    notes?: string;
  }) {
    return this.request<any>('/wholesale-pos/pos/checkout/', {
      method: 'POST',
      body: JSON.stringify(data),
    });
  }

  async getProformas() {
    return this.request<any[]>('/wholesale-pos/proformas/');
  }

  async createProforma(data: any) {
    return this.request<any>('/wholesale-pos/proformas/', {
      method: 'POST',
      body: JSON.stringify(data),
    });
  }

  async convertProformaToOrder(proformaId: string) {
    return this.request<any>(`/wholesale-pos/proformas/${proformaId}/convert-to-order/`, {
      method: 'POST',
    });
  }

  // Audit, Notifications & Reports
  async getNotifications(isRead?: boolean) {
    const query = isRead !== undefined ? `?is_read=${isRead}` : '';
    return this.request<any[]>(`/audit/notifications/${query}`);
  }

  async markNotificationRead(id: string) {
    return this.request<any>(`/audit/notifications/${id}/read/`, {
      method: 'POST',
    });
  }

  async markAllNotificationsRead() {
    return this.request<any>('/audit/notifications/read-all/', {
      method: 'POST',
    });
  }

  async getNotificationPreferences() {
    return this.request<any>('/audit/preferences/');
  }

  async updateNotificationPreferences(data: any) {
    return this.request<any>('/audit/preferences/', {
      method: 'PUT',
      body: JSON.stringify(data),
    });
  }

  async getTeamActivitySummary(days: number = 30) {
    return this.request<any>(`/audit/team-activity/?days=${days}`);
  }

  getAuditExportCSVUrl() {
    return `${API_BASE_URL}/audit/export-csv/`;
  }
}

export const api = new ApiClient();

