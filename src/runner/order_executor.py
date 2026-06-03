"""Execute an approved daily decision: place Kalshi order, log to DB and CSV."""
import csv
import logging
import os
from datetime import datetime, timezone
from decimal import Decimal

logger = logging.getLogger(__name__)

ORDERS_CSV = os.environ.get('ORDERS_CSV', 'orders.csv')
CSV_FIELDS = [
    'timestamp', 'ticker', 'side', 'action', 'count',
    'price_cents', 'kalshi_order_id', 'status', 'notes',
]


def _ensure_csv_header():
    if not os.path.exists(ORDERS_CSV):
        with open(ORDERS_CSV, 'w', newline='') as f:
            csv.DictWriter(f, fieldnames=CSV_FIELDS).writeheader()


def _append_csv(row: dict):
    _ensure_csv_header()
    with open(ORDERS_CSV, 'a', newline='') as f:
        csv.DictWriter(f, fieldnames=CSV_FIELDS).writerow(row)


def execute_decision(session, decision_id: int, kalshi_client) -> bool:
    """Place the Kalshi order for an approved daily_decision row.

    Updates the decision status and creates an Order record.
    Returns True on success, False on failure.
    """
    from sqlalchemy import select
    from sqlalchemy.dialects.postgresql import insert as pg_insert
    from db.models import DailyDecision, Order

    decision = session.get(DailyDecision, decision_id)
    if decision is None:
        logger.error('Decision %d not found', decision_id)
        return False
    if decision.status != 'approved':
        logger.warning('Decision %d status is %s, expected approved', decision_id, decision.status)
        return False

    # Parse recommended_action: 'buy_yes' or 'buy_no'
    action_parts = decision.recommended_action.split('_')
    if len(action_parts) != 2 or action_parts[0] != 'buy':
        logger.warning('Unexpected action %s', decision.recommended_action)
        decision.status = 'rejected'
        session.commit()
        return False

    side = action_parts[1]          # 'yes' or 'no'
    action = 'buy'
    count = int(decision.confidence * 100)  # repurposed: confidence field stores n_contracts
    price_cents = int(float(decision.forecast or 0))

    if count < 1 or price_cents < 1 or price_cents > 99:
        logger.warning('Invalid order params: count=%d price=%d¢', count, price_cents)
        decision.status = 'rejected'
        session.commit()
        return False

    now = datetime.now(tz=timezone.utc)
    kalshi_order_id = None
    status = 'EXECUTED'
    notes = f'decision_id={decision_id}'

    try:
        resp = kalshi_client.place_order(
            ticker=decision.ticker,
            side=side,
            action=action,
            count=count,
            price_cents=price_cents,
        )
        order_data = resp.get('order', {})
        kalshi_order_id = order_data.get('order_id') or order_data.get('client_order_id')
        logger.info(
            'Order placed: %s %s %d × %s @ %d¢  kalshi_id=%s',
            action, side, count, decision.ticker, price_cents, kalshi_order_id,
        )
    except Exception as exc:
        logger.error('Order placement failed: %s', exc)
        status = 'FAILED'
        notes += f' | error={exc}'

    # Write to orders table
    order = Order(
        ticker=decision.ticker,
        side=f'{side}_{action}',
        quantity=count,
        price=Decimal(str(price_cents)) / 100,
        status=status,
        created_at=now,
        executed_at=now if status == 'EXECUTED' else None,
        notes=notes,
    )
    session.add(order)

    # Write to CSV
    _append_csv({
        'timestamp': now.isoformat(),
        'ticker': decision.ticker,
        'side': side,
        'action': action,
        'count': count,
        'price_cents': price_cents,
        'kalshi_order_id': kalshi_order_id or '',
        'status': status,
        'notes': notes,
    })

    decision.status = 'executed' if status == 'EXECUTED' else 'failed'
    session.commit()
    logger.info('Decision %d → %s', decision_id, decision.status)
    return status == 'EXECUTED'
