import asyncio
from datetime import date, datetime, timedelta

import aiohttp
from telegram import BotCommand, Update
from telegram.ext import (
    Application,
    ApplicationBuilder,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    ConversationHandler,
    MessageHandler,
    filters,
)
from telegram_bot_calendar import DetailedTelegramCalendar

from app.config.config import config

STOCK, DATE, INVESTMENT = range(3)


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    await update.message.reply_text("Which stock do you want to regret?")
    return STOCK


async def stock(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    stock_name = update.message.text
    context.user_data["stock_name"] = stock_name
    calendar, step = DetailedTelegramCalendar().build()
    await update.message.reply_text(
        f"When do you regret you should have invested in {stock_name}?\n\nSelect {step}:",
        reply_markup=calendar,
    )
    return DATE


async def fetch_price_at_date(stock: str, date: str):
    try:
        url = f"{config.gofinance_base_url}/price"

        async with session.get(
            url=url, params={"company": stock, "date": date}
        ) as response:
            response.raise_for_status()
            data = await response.json()
            return data

    except Exception as e:
        print(e)
        return None


async def fetch_forex_at_date(base_currency: str, date: str):
    try:
        url = f"{config.gofinance_base_url}/forex"

        async with session.get(
            url=url, params={"base_currency": base_currency, "date": date}
        ) as response:
            response.raise_for_status()
            data = await response.json()
            return data

    except Exception as e:
        print(e)
        return None


async def get_fx_rate_on_or_before(
    currency: str,
    target_date: str,
    max_lookback_days: int = 10,
):
    if currency == "INR":
        return 1.0

    dt = datetime.strptime(target_date, "%Y-%m-%d").date()

    for _ in range(max_lookback_days):
        data = await fetch_forex_at_date(
            base_currency="INR",
            date=dt.isoformat(),
        )

        if data:
            for row in data:
                if row["quote"] == currency:
                    return row["rate"]

        dt -= timedelta(days=1)

    return None


async def fetch_price_on_or_before(
    stock: str, target_date: str, max_lookback_days: int = 10
):

    dt = datetime.strptime(target_date, "%Y-%m-%d").date()

    for _ in range(max_lookback_days):
        data = await fetch_price_at_date(
            stock=stock,
            date=dt.isoformat(),
        )

        if data and data.get("price") is not None:
            data["effective_date"] = dt.isoformat()
            return data

        dt -= timedelta(days=1)

    return None


async def calculate_current_value(
    stock: str,
    investment: float,
    invested_date: str,
):

    today = date.today().isoformat()

    today_data, investment_data = await asyncio.gather(
        fetch_price_on_or_before(
            stock=stock,
            target_date=today,
        ),
        fetch_price_on_or_before(
            stock=stock,
            target_date=invested_date,
        ),
    )
    if not today_data:
        return {"error": "Unable to fetch current stock price."}

    if not investment_data:
        return {"error": f"{stock} was not publicly traded on {invested_date}."}

    price_today = today_data["price"]

    price_at_investment = investment_data["price"]

    currency = investment_data["currency"]
    # Indian stock

    if currency == "INR":
        shares_bought = investment / price_at_investment

        current_value = shares_bought * price_today

        return {
            "current_value": round(current_value, 2),
            "symbol": investment_data["symbol"],
            "currency": currency,
            "buy_price": round(price_at_investment, 2),
            "current_price": round(price_today, 2),
        }

    investment_fx_rate, current_fx_rate = await asyncio.gather(
        get_fx_rate_on_or_before(
            currency=currency,
            target_date=investment_data["effective_date"],
        ),
        get_fx_rate_on_or_before(
            currency=currency,
            target_date=today_data["effective_date"],
        ),
    )

    if not investment_fx_rate or not current_fx_rate:
        return {"error": "Unable to fetch forex data."}

    # INR -> stock currency

    investment_in_stock_currency = investment * investment_fx_rate

    shares_bought = investment_in_stock_currency / price_at_investment

    current_value_stock_currency = shares_bought * price_today

    # stock currency -> INR

    current_value_inr = current_value_stock_currency / current_fx_rate

    return {
        "current_value": round(current_value_inr, 2),
        "symbol": investment_data["symbol"],
        "currency": currency,
        "buy_price": round(price_at_investment, 2),
        "current_price": round(price_today, 2),
    }


async def calendar_handler(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> int:

    query = update.callback_query

    await query.answer()

    result, keyboard, _ = DetailedTelegramCalendar().process(query.data)

    if not result and keyboard:
        await query.edit_message_reply_markup(
            reply_markup=keyboard,
        )

        return DATE

    if result:
        context.user_data["date_str"] = result.isoformat()

        await query.edit_message_text(f"📅 Selected date: {result}")

        await query.message.reply_text(
            "How much do you want to regret not investing in this stock?"
        )

        return INVESTMENT

    return DATE


async def investment(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> int:

    try:
        amount = float(update.message.text)

    except ValueError:
        await update.message.reply_text("Please enter a valid number.")

        return INVESTMENT

    stock_name = context.user_data["stock_name"]

    investment_date = context.user_data["date_str"]
    placeholder = await update.message.reply_text("⏳ Calculating your regret...")

    result = await calculate_current_value(
        investment=amount,
        stock=stock_name,
        invested_date=investment_date,
    )

    if "error" in result:
        await update.message.reply_text(result["error"])
        return ConversationHandler.END

    current_value = result["current_value"]

    profit = current_value - amount

    return_pct = (profit / amount) * 100
    title = f"{stock_name.title()} ({result['symbol']})"

    formatted_date = datetime.strptime(
        investment_date,
        "%Y-%m-%d",
    ).strftime("%d %b %Y")

    if profit > 0:
        if profit > 1000:
            heading = "💀 Generational Fumble"
        else:
            heading = "😬 Missed Opportunity"
    elif profit < 0:
        if profit < -50:
            heading = "🫡 Thank Your Lucky Stars"
        else:
            heading = "📉 Dodged a Bullet"
    else:
        heading = "😐 Perfect Timing"

    await placeholder.edit_text(
        f"""{heading}

{title}

₹{amount:,.0f} → ₹{current_value:,.0f}

Profit: ₹{profit:,.0f}
Return: {return_pct:+.2f}%

────────────
Invested: {formatted_date}
Buy Price: {result["buy_price"]:,.2f} {result["currency"]}
Today: {result["current_price"]:,.2f} {result["currency"]}
"""
    )
    return ConversationHandler.END


async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Cancels and ends the conversation."""
    await update.message.reply_text(
        "Bye! I hope we can talk again some day.",
    )

    return ConversationHandler.END


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):

    await update.message.reply_text(
        """

📚 Available Commands

/start - Start the bot

/help - Show this help message

/cancel - Cancel current operation

Workflow:

1. Enter stock symbol

2. Select date

3. Enter investment amount

        """
    )


async def post_init(application: Application):
    global session

    headers = {
        "Authorization": aiohttp.encode_basic_auth(
            config.gofinance_username,
            config.gofinance_password,
        )
    }

    session = aiohttp.ClientSession(
        headers=headers,
        timeout=aiohttp.ClientTimeout(total=30),
    )

    await application.bot.set_my_commands(
        [
            BotCommand("start", "Start the bot"),
            BotCommand("help", "Show help information"),
            BotCommand("cancel", "Cancel current operation"),
        ]
    )


async def post_shutdown(application: Application):

    global session

    if session:
        await session.close()


if __name__ == "__main__":
    application = (
        ApplicationBuilder()
        .token(config.bot_token)
        .post_init(post_init)
        .post_shutdown(post_shutdown)
        .build()
    )

    conv_handler = ConversationHandler(
        entry_points=[CommandHandler("start", start)],
        states={
            STOCK: [MessageHandler(filters.TEXT & ~filters.COMMAND, stock)],
            DATE: [CallbackQueryHandler(calendar_handler)],
            INVESTMENT: [MessageHandler(filters.TEXT & ~filters.COMMAND, investment)],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
    )
    application.add_handler(conv_handler)
    application.add_handler(CommandHandler("help", help_command))

    application.run_polling(allowed_updates=Update.ALL_TYPES)
