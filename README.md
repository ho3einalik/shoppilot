# ShopPilot (شاپ‌پایلوت) 🚀

ShopPilot is a production-oriented, modular, multi-tenant SaaS platform engineered for managing and optimizing multi-channel online and social commerce businesses (Instagram, Telegram, WooCommerce, physical stores).

> 📖 **مستند کامل قابلیت‌ها و امکانات:** برای مطالعه فهرست کامل و جزییات تمامی ماژول‌ها و امکانات اضافه شده، فایل [FEATURES.md](./FEATURES.md) را مشاهده فرمایید.

---

## Key Modules & Capabilities

- **External Integrations Center (مرکز اتصال‌ها):** Centralized, encrypted management of SMS (Kavenegar), Instagram Meta Graph API, Zarinpal payment gateway, Iran Post/Tipax shipping, Gemini AI, and SMTP email with server-side live testing and SSRF protection.
- **Multi-Tenancy & RBAC:** Multi-business, multi-store architecture with strict data isolation, role-based access control, and audit logs.
- **Product Catalog:** Products, variants (SKU/barcodes), categories, cost & retail price tracking in Iranian Toman (IRT) and Rial (IRR).
- **Inventory & Warehouses:** Concurrency-safe stock management, multi-warehouse support, atomic reservations, double-entry inventory ledger.
- **Orders & Multi-Channel Fulfillment:** Unified orders, state transitions, shipments with tracking numbers, packing slips, and CSV imports.
- **Payments & Verification:** Gateways, payment links, and a dedicated review workflow for manual card-to-card transfers.
- **Daily Action Center:** Actionable alerts (stockouts, pending approvals, fulfillment delays) backed by evidence.
- **Sales & Profit Analytics:** Real-time metrics with historical cost snapshots to calculate true gross profit.
- **Persian RTL Frontend:** Next.js 14 dashboard with native right-to-left UI, Persian typography, and responsive views.

---

## Tech Stack

- **Backend:** Python 3.13, Django 5.x, Django REST Framework, SimpleJWT, Celery/Redis.
- **Frontend:** Next.js 14 (App Router), React, TypeScript, Tailwind CSS, Lucide Icons, RTL support.
- **Database:** PostgreSQL (with SQLite development fallback).
- **Testing:** Pytest with extensive tenant isolation and concurrency tests.

---

## Quickstart

### Prerequisites
- Python 3.11+
- Node.js 18+ and npm
- (Optional) Docker & Docker Compose

### 1. Backend Setup
```bash
cd backend
python -m venv venv
# On Windows:
.\venv\Scripts\activate
# On Linux/macOS:
source venv/bin/activate

pip install -r requirements.txt
python manage.py migrate
python manage.py seed_demo_data
python manage.py runserver 8000
```

### 2. Frontend Setup
```bash
cd frontend
npm install
npm run dev
```
Open [http://localhost:3000](http://localhost:3000) to access the ShopPilot cockpit.
