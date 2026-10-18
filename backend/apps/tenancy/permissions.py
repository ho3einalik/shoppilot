import uuid
from rest_framework import permissions, filters
from .models import Role, StoreMembership, MembershipStatus

def get_request_store(request):
    """Dynamically resolves and caches request.store and request.membership for DRF/Django requests.
    Enforces active store and active membership status (rejects suspended memberships)."""
    if getattr(request, 'store', None) and getattr(request, 'membership', None):
        # Validate that cached membership is still active
        if request.membership.is_active and request.membership.status == MembershipStatus.ACTIVE:
            return request.store
        request.store = None
        request.membership = None
        return None

    if not (getattr(request, 'user', None) and request.user.is_authenticated):
        request.store = None
        request.membership = None
        return None

    store = None
    membership = None
    raw_store_id = (
        request.headers.get('x-store-id')
        or request.META.get('HTTP_X_STORE_ID')
        or request.GET.get('store_id')
    )

    if raw_store_id:
        try:
            valid_uuid = uuid.UUID(str(raw_store_id).strip())
        except (ValueError, AttributeError, TypeError):
            request.store = None
            request.membership = None
            return None

        membership = StoreMembership.objects.select_related('store').filter(
            user=request.user,
            store_id=valid_uuid,
            is_active=True,
            status=MembershipStatus.ACTIVE,
            store__is_active=True
        ).first()
        if membership:
            store = membership.store
        elif request.user.is_superuser or request.user.is_staff:
            from .models import Store
            store = Store.objects.filter(id=valid_uuid, is_active=True).first()
            if not store:
                request.store = None
                request.membership = None
                return None
        else:
            # Explicit store requested but user has no active membership in it -> fail-closed
            request.store = None
            request.membership = None
            return None
    else:
        # No header specified: default to user's first active store
        membership = StoreMembership.objects.select_related('store').filter(
            user=request.user,
            is_active=True,
            status=MembershipStatus.ACTIVE,
            store__is_active=True
        ).order_by('created_at').first()
        if membership:
            store = membership.store
        elif request.user.is_superuser or request.user.is_staff:
            from .models import Store
            store = Store.objects.filter(is_active=True).order_by('created_at').first()

    request.store = store
    request.membership = membership
    return store


ROLE_DEFAULT_PERMISSIONS = {
    Role.OWNER: ['*'],
    Role.ADMIN: ['*'],
    Role.BUSINESS_MANAGER: [
        'team.view', 'team.invite', 'team.manage_roles', 'team.remove',
        'tasks.view_all', 'tasks.create', 'tasks.assign', 'tasks.edit', 'tasks.complete', 'tasks.verify',
        'content.view', 'content.create', 'content.edit', 'content.submit', 'content.approve', 'content.reject',
        'analytics.view', 'analytics.export', 'settings.manage'
    ],
    Role.SOCIAL_MEDIA_MANAGER: [
        'tasks.view_all', 'tasks.create', 'tasks.assign', 'tasks.edit', 'tasks.complete',
        'content.view', 'content.create', 'content.edit', 'content.submit', 'content.approve', 'content.reject', 'content.publish',
        'analytics.view', 'analytics.export', 'integrations.manage'
    ],
    Role.CONTENT_CREATOR: [
        'tasks.view_assigned', 'tasks.complete',
        'content.view', 'content.create', 'content.edit', 'content.submit'
    ],
    Role.OPS_MANAGER: [
        'tasks.view_all', 'tasks.create', 'tasks.assign', 'tasks.edit', 'tasks.complete', 'tasks.verify',
        'analytics.view', 'inventory.view', 'orders.view', 'fulfillment.manage'
    ],
    Role.INVENTORY_MANAGER: [
        'inventory.view', 'inventory.adjust', 'inventory.receive', 'inventory.transfer',
        'tasks.view_assigned', 'tasks.complete', 'suppliers.view', 'suppliers.receive'
    ],
    Role.FULFILLMENT_STAFF: [
        'tasks.view_assigned', 'tasks.complete', 'fulfillment.view', 'fulfillment.pack'
    ],
    Role.SUPPORT: [
        'tasks.view_assigned', 'tasks.complete', 'crm.view', 'social_inbox.view'
    ],
    Role.READ_ONLY: [
        'team.view', 'tasks.view_all', 'content.view', 'analytics.view'
    ],
    Role.CUSTOM: []
}

def user_has_store_permission(membership, perm_code):
    if not membership or not membership.is_active or getattr(membership, 'status', 'ACTIVE') != MembershipStatus.ACTIVE:
        return False
    if membership.role in [Role.OWNER, Role.ADMIN]:
        return True
    defaults = ROLE_DEFAULT_PERMISSIONS.get(membership.role, [])
    if '*' in defaults or perm_code in defaults:
        return True
    return perm_code in (getattr(membership, 'custom_permissions', None) or [])

class IsStoreMemberPermission(permissions.BasePermission):
    """Requires request to have an active store context and active membership"""
    message = "دسترسی به این فروشگاه مجاز نیست، عضویت شما معلق است یا فروشگاه انتخاب نشده است."

    def has_permission(self, request, view):
        if not (request.user and request.user.is_authenticated):
            return False
        store = get_request_store(request)
        if request.user.is_superuser or request.user.is_staff:
            return True
        membership = getattr(request, 'membership', None)
        if not (store and membership):
            return False
        if not (membership.is_active and membership.status == MembershipStatus.ACTIVE and store.is_active):
            return False
        if request.method not in permissions.SAFE_METHODS and membership.role == Role.READ_ONLY:
            self.message = "کاربر با نقش فقط‌خواندنی (READ_ONLY) مجاز به ثبت، تغییر یا حذف اطلاعات نیست."
            return False
        return True

class IsStoreAdminOrOwnerPermission(permissions.BasePermission):
    """Requires user to be active OWNER, ADMIN, or BUSINESS_MANAGER of the active store (or platform staff)"""
    message = "این عملیات نیازمند سطح دسترسی مدیر یا مالک فروشگاه است."

    def has_permission(self, request, view):
        if not (request.user and request.user.is_authenticated):
            return False
        store = get_request_store(request)
        if request.user.is_superuser or request.user.is_staff:
            return True
        membership = getattr(request, 'membership', None)
        if not (store and membership):
            return False
        if not (membership.is_active and membership.status == MembershipStatus.ACTIVE and store.is_active):
            return False
        return bool(membership.role in [Role.OWNER, Role.ADMIN, Role.BUSINESS_MANAGER])


class HasStorePermission(permissions.BasePermission):
    """Verifies that the user's role or custom permissions include the required permission"""
    def __init__(self, required_permission=None):
        self.required_permission = required_permission

    def has_permission(self, request, view):
        store = get_request_store(request)
        membership = getattr(request, 'membership', None)
        if not (request.user and request.user.is_authenticated and store and membership):
            return False
        if not (membership.is_active and membership.status == MembershipStatus.ACTIVE and store.is_active):
            return False
        perm = getattr(view, 'required_permission', self.required_permission)
        if not perm:
            return True
        return user_has_store_permission(membership, perm)

class TenantFilterBackend(filters.BaseFilterBackend):
    """Restricts queryset strictly to the store bound to the current request"""
    def filter_queryset(self, request, queryset, view):
        store = get_request_store(request)
        if store and hasattr(queryset.model, 'store'):
            return queryset.filter(store=store)
        return queryset.none()


