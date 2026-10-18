from django.utils import timezone
from .models import ConversationThread, ChatMessage, SenderType, ThreadStatus
from apps.catalog.models import ProductVariant
from apps.features.adapters import get_integration_adapter

def generate_ai_suggested_reply(thread, context_hint=''):
    """
    Generate an AI draft response grounded in the store's verified product catalog and store inventory.
    """
    store = thread.store
    # Grab latest customer messages
    recent_messages = thread.messages.order_by('-created_at')[:4]
    customer_query = ""
    for msg in reversed(list(recent_messages)):
        customer_query += f"{msg.sender_type}: {msg.text}\n"

    # Fetch top active products for catalog grounding
    products = ProductVariant.objects.filter(store=store, is_active=True).select_related('product')[:5]
    catalog_context = "\n".join([
        f"- {p.product.name} ({p.sku}): قیمت {p.retail_price:,} {store.currency}"
        for p in products
    ])

    # Fetch customer's recent orders if available
    customer = getattr(thread, 'customer', None)
    orders_context = ""
    if customer:
        from apps.orders.models import Order
        recent_orders = Order.objects.filter(store=store, customer=customer).order_by('-created_at')[:2]
        if recent_orders.exists():
            orders_context = "\nآخرین وضعیت سفارشات مشتری:\n" + "\n".join([
                f"- سفارش {o.order_number}: وضعیت ارسال={o.get_fulfillment_status_display()}، وضعیت پرداخت={o.get_payment_status_display()}، مبلغ={o.grand_total:,} {store.currency}"
                for o in recent_orders
            ])

    prompt = f"""
شما پشتیبان فروشگاه {store.name} در دایرکت هستید.
مخاطب: {thread.contact_name} ({thread.contact_handle})
تاریخچه گفتگو:
{customer_query}

محصولات برگزیده در دسترس فروشگاه:
{catalog_context}
{orders_context}

لطفاً یک پاسخ بسیار محترمانه، صمیمی، دقیق و مختصر بنویسید. در صورتی که قیمت پرسیده شده، قیمت دقیق موجود در کاتالوگ را بگویید و اعلام کنید ارسال از طریق پست پیشتاز و تیپاکس به سراسر کشور انجام می‌شود.
"""

    adapter = get_integration_adapter('ai_provider')
    res = adapter.generate_caption_or_text(prompt=prompt, tone='friendly')
    suggested_text = res.get('text', '')

    if not suggested_text:
        # Heuristic reliable fallback
        suggested_text = (
            f"سلام {thread.contact_name} عزیز، وقت بخیر! 🌸\n"
            f"ممنون از پیامتون به {store.name}.\n"
            f"سفارش شما با نهایت دقت ثبت و با پست پیشتاز/تیپاکس ارسال خواهد شد. در صورت نیاز به راهنمایی در مورد هر کدام از محصولات در خدمتتون هستیم!"
        )

    return {
        'suggested_text': suggested_text.strip(),
        'source': res.get('source', 'heuristic_fallback')
    }

def send_agent_message(thread, text, user=None, is_ai=False, was_edited=False):
    """
    Saves and dispatches an agent/assistant message to the external customer channel.
    Connects to Meta Graph API for Instagram DM and Telegram Bot API for Telegram.
    """
    from .models import ThreadChannel

    msg = ChatMessage.objects.create(
        thread=thread,
        sender_type=SenderType.AGENT,
        sender_user=user,
        text=text,
        is_ai_generated=is_ai,
        was_edited_by_human=was_edited,
        delivery_status='SENT'
    )

    store = thread.store

    # 1. Instagram Direct Message dispatch
    if thread.channel == ThreadChannel.INSTAGRAM_DM:
        ig_adapter = get_integration_adapter('social_instagram')
        if ig_adapter and thread.contact_handle:
            res = ig_adapter.send_direct_message(store=store, recipient_id=thread.contact_handle, text=text)
            if res.get('status') == 'DELIVERED':
                msg.delivery_status = 'DELIVERED'
                msg.external_message_id = res.get('message_id', '')
            else:
                msg.delivery_status = res.get('status', 'FAILED')
                msg.error_message = res.get('error', '')
        else:
            msg.delivery_status = 'LOCAL_ONLY'
            msg.error_message = 'اتصال اینستاگرام یا آیدی گیرنده تنظیم نشده است.'

    # 2. Telegram Bot dispatch
    elif thread.channel == ThreadChannel.TELEGRAM:
        tg_adapter = get_integration_adapter('social_telegram')
        if tg_adapter and thread.contact_handle:
            res = tg_adapter.send_message(store=store, chat_id=thread.contact_handle, text=text)
            if res.get('status') == 'DELIVERED':
                msg.delivery_status = 'DELIVERED'
                msg.external_message_id = res.get('message_id', '')
            else:
                msg.delivery_status = 'FAILED'
                msg.error_message = res.get('error', '')
        else:
            msg.delivery_status = 'LOCAL_ONLY'
            msg.error_message = 'ربات تلگرام یا شناسه چت تنظیم نشده است.'

    # 3. Web chat / Other
    else:
        msg.delivery_status = 'DELIVERED'

    msg.save(update_fields=['delivery_status', 'external_message_id', 'error_message'])

    thread.last_message_preview = text[:200]
    thread.status = ThreadStatus.PENDING_CUSTOMER
    thread.unread_count = 0
    thread.last_message_at = timezone.now()
    thread.save()
    return msg


def receive_incoming_message(store, channel, sender_id, sender_name, text, external_message_id=None, media_url=''):
    """
    Idempotently records an incoming message from external webhook (Instagram DM, Telegram, etc.)
    and updates conversation thread state.
    """
    if external_message_id:
        existing = ChatMessage.objects.filter(external_message_id=external_message_id).first()
        if existing:
            return existing

    thread, _ = ConversationThread.objects.get_or_create(
        store=store,
        channel=channel,
        contact_handle=sender_id,
        defaults={
            'contact_name': sender_name or f"کاربر {sender_id}",
            'status': ThreadStatus.OPEN
        }
    )

    msg = ChatMessage.objects.create(
        thread=thread,
        sender_type=SenderType.CUSTOMER,
        text=text,
        media_url=media_url,
        external_message_id=external_message_id or '',
        delivery_status='DELIVERED'
    )

    thread.last_message_preview = text[:200]
    thread.status = ThreadStatus.OPEN
    thread.unread_count = (thread.unread_count or 0) + 1
    thread.last_message_at = timezone.now()
    thread.save(update_fields=['last_message_preview', 'status', 'unread_count', 'last_message_at'])
    return msg
