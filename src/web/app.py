"""FastAPI + HTMX + Jinja2 web application."""
import os
import sys
from datetime import datetime, timezone, date

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', 'src'))

from fastapi import FastAPI, Request, Form, HTTPException
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlalchemy import select, func, text

from db.models import DailyDecision, Order, MarketStats, ModelResult, MarketPrice
from db.session import get_session
from runner.order_executor import execute_decision
from kalshi.client import KalshiClient

BASE_DIR = os.path.dirname(__file__)
templates = Jinja2Templates(directory=os.path.join(BASE_DIR, 'templates'))

app = FastAPI(title='Kalshi Forecasting Dashboard')


# ── Helpers ───────────────────────────────────────────────────────────────────

def _fmt_cents(v):
    if v is None:
        return '—'
    return f'{float(v):.1f}¢'

def _fmt_dollars(v):
    if v is None:
        return '—'
    return f'${float(v):.2f}'

templates.env.filters['cents'] = _fmt_cents
templates.env.filters['dollars'] = _fmt_dollars


# ── Routes ────────────────────────────────────────────────────────────────────

@app.get('/', response_class=HTMLResponse)
def dashboard(request: Request):
    session = get_session()
    try:
        # Recent decisions
        decisions = session.execute(
            select(DailyDecision)
            .order_by(DailyDecision.date.desc())
            .limit(10)
        ).scalars().all()

        # Open positions via Kalshi
        positions = []
        try:
            with KalshiClient() as client:
                balance = client.get_balance()
                positions = client.get_positions()
                balance_cents = balance.available_balance_cents
        except Exception:
            balance_cents = 0

        # P&L from executed orders
        total_pnl = session.scalar(
            select(func.sum(Order.pnl)).where(Order.pnl.isnot(None))
        ) or 0

        # Pending count
        pending_count = session.scalar(
            select(func.count(DailyDecision.id))
            .where(DailyDecision.status == 'pending')
        ) or 0

        return templates.TemplateResponse(request, 'dashboard.html', {
            'decisions': decisions,
            'positions': positions,
            'balance_cents': balance_cents,
            'total_pnl': total_pnl,
            'pending_count': pending_count,
            'now': datetime.now(tz=timezone.utc),
        })
    finally:
        session.close()


@app.get('/decisions', response_class=HTMLResponse)
def decisions_page(request: Request):
    session = get_session()
    try:
        pending = session.execute(
            select(DailyDecision)
            .where(DailyDecision.status == 'pending')
            .order_by(DailyDecision.date.desc())
        ).scalars().all()

        recent = session.execute(
            select(DailyDecision)
            .where(DailyDecision.status != 'pending')
            .order_by(DailyDecision.date.desc())
            .limit(20)
        ).scalars().all()

        return templates.TemplateResponse(request, 'decisions.html', {
            'pending': pending,
            'recent': recent,
        })
    finally:
        session.close()


@app.post('/decisions/{decision_id}/approve', response_class=HTMLResponse)
def approve_decision(request: Request, decision_id: int):
    session = get_session()
    try:
        decision = session.get(DailyDecision, decision_id)
        if decision is None:
            raise HTTPException(404, 'Decision not found')
        if decision.status != 'pending':
            raise HTTPException(400, f'Decision is already {decision.status}')

        decision.status = 'approved'
        session.flush()

        with KalshiClient() as client:
            success = execute_decision(session, decision_id, client)

        status_text = 'executed ✓' if success else 'failed ✗'
        return HTMLResponse(
            f'<span class="badge badge-{"success" if success else "error"}">'
            f'{status_text}</span>'
        )
    finally:
        session.close()


@app.post('/decisions/{decision_id}/reject', response_class=HTMLResponse)
def reject_decision(request: Request, decision_id: int):
    session = get_session()
    try:
        decision = session.get(DailyDecision, decision_id)
        if decision is None:
            raise HTTPException(404, 'Decision not found')
        decision.status = 'rejected'
        session.commit()
        return HTMLResponse('<span class="badge badge-neutral">rejected</span>')
    finally:
        session.close()


@app.get('/history', response_class=HTMLResponse)
def history(request: Request):
    session = get_session()
    try:
        orders = session.execute(
            select(Order).order_by(Order.created_at.desc()).limit(100)
        ).scalars().all()
        return templates.TemplateResponse(request, 'history.html', {
            'orders': orders,
        })
    finally:
        session.close()


@app.get('/models', response_class=HTMLResponse)
def models_page(request: Request):
    session = get_session()
    try:
        results = session.execute(
            select(ModelResult)
            .order_by(ModelResult.sharpe.desc())
            .limit(50)
        ).scalars().all()
        return templates.TemplateResponse(request, 'models.html', {
            'results': results,
        })
    finally:
        session.close()


@app.get('/settings', response_class=HTMLResponse)
def settings(request: Request):
    import os
    cfg = {
        'BUDGET_DOLLARS': os.environ.get('BUDGET_DOLLARS', '100.0'),
        'MIN_CANDLES': os.environ.get('MIN_CANDLES', '90'),
        'TC_CENTS': os.environ.get('TC_CENTS', '1.0'),
        'ORDERS_CSV': os.environ.get('ORDERS_CSV', 'orders.csv'),
        'TICKER': 'KXLEAVESTARMER-26JUL01',
    }
    return templates.TemplateResponse(request, 'settings.html', {
        'cfg': cfg,
    })
