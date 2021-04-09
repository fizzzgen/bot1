"""
This is a echo bot.
It echoes any incoming text messages.
"""

import asyncio
import asyncpg
import logging
import httpx
import pprint
import time
import os

from aiogram import Bot, Dispatcher, executor, types
from aiogram.types.message import ContentTypes

API_TOKEN = os.environ['TELEGRAM_BOT_TOKEN']
PAYMENTS_PROVIDER_TOKEN = os.environ['PAYMENTS_PROVIDER_TOKEN']
DATABASE_URL = os.environ['DATABASE_URL']
pool = None

# Configure logging
logging.basicConfig(level=logging.INFO)

# Initialize bot and dispatcher
bot = Bot(token=API_TOKEN)
dp = Dispatcher(bot)

update_time = 0

# Setup prices
prices = [
    types.LabeledPrice(label='Продление подписки на месяц', amount=10000),
]


async def update_status(alert, status, chat_id, error=None):
    db = await asyncpg.connect(DATABASE_URL)
    await db.execute('''UPDATE ALERTS SET status=$1 WHERE id=$2''', *[status, alert[0], ])
    if error:
        await db.execute('''UPDATE ALERTS SET latest_error=$1 WHERE id=$2''', *[str(error).replace('\n', ' '), alert[0], ])
    await db.commit()
    await db.close()
    if alert[5] != status and 'HTTP_ERROR' not in status and 'HTTP_ERROR' not in alert[5]:
        await bot.send_message(chat_id, '‼️‼️‼️ Мониторинг {} сменил статус на {}'.format(alert[2], status))


async def update_alerts():
    global update_time
    t1 = time.time()
    client = httpx.AsyncClient()
    db = await asyncpg.connect(DATABASE_URL)
    alerts = await db.fetch('''SELECT id, chat_id, name, address, template, status FROM ALERTS''')
    await db.close()
    req_coros = []
    for alert in alerts:
        req_coros.append(client.get(alert[3], timeout=5))

    req_coros = await asyncio.gather(*req_coros, return_exceptions=True)
    alert_id = 0
    for coro in req_coros:
        try:
            resp = coro
            if resp.status_code != 200:
                await update_status(alerts[alert_id], '🛠HTTP_ERROR:{}🛠'.format(resp.status_code), alerts[alert_id][1], error=resp.text)
            if alerts[alert_id][4] in resp.text:
                await update_status(alerts[alert_id], '✅TEMPLATE_FOUND✅', alerts[alert_id][1])
            else:
                await update_status(alerts[alert_id], '🚫TEMPLATE_NOT_FOUND🚫', alerts[alert_id][1])
        except Exception as ex:
            await update_status(alerts[alert_id], '🛠HTTP_ERROR🛠', alerts[alert_id][1], error=ex)
        alert_id += 1
    t2 = time.time()
    update_time = t2 - t1



async def updater():
    while True:
        await update_alerts()
        await asyncio.sleep(5)

async def on_startup(x):
    global pool
    pool = await asyncpg.create_pool(DATABASE_URL)
    db = await asyncpg.connect(DATABASE_URL)

    await db.execute('''CREATE TABLE IF NOT EXISTS ALERTS(
                    id serial PRIMARY KEY,
                    chat_id INTEGER,
                    name TEXT,
                    address TEXT,
                    template TEXT,
                    status TEXT,
                    latest_error TEXT
                    )''')
    await db.execute('''CREATE TABLE IF NOT EXISTS PAYMENTS(
                    chat_id serial PRIMARY KEY,
                    ts INTEGER,
                    amount INTEGER
                    )''')
    await db.close()
    asyncio.create_task(updater())


async def get_payment_ts(chat_id):
    db = await asyncpg.connect(DATABASE_URL)
    users = await db.fetch('''SELECT ts FROM PAYMENTS WHERE chat_id=$1''', *[chat_id, ])
    await db.close()
    if not users:
        return 0
    return max([users[i][0] for i in range(len(users))])


async def add_payment(chat_id, amount=100):
    db = await asyncpg.connect(DATABASE_URL)
    await db.execute('''INSERT INTO PAYMENTS(chat_id, ts, amount) VALUES($1,$2,$3)''', *[chat_id, int(time.time()), amount])
    await db.close()


async def add(chat_id, name, address, template):
    db = await asyncpg.connect(DATABASE_URL)
    await db.execute('''INSERT INTO ALERTS(chat_id, name, address, template, status) VALUES($1,$2,$3,$4,$5)''', *[chat_id, name, address, template, '⏳NS⏳'])
    await db.close()


async def delete(chat_id, name):
    db = await asyncpg.connect(DATABASE_URL)
    await db.execute('''DELETE FROM ALERTS WHERE chat_id=$1 AND name=$2''', *[chat_id, name])
    await db.close()


async def status(chat_id):
    db = await asyncpg.connect(DATABASE_URL)
    alerts = await db.fetch('''SELECT status, name, address, template, latest_error FROM ALERTS WHERE chat_id=$1''', *[chat_id, ])
    await db.close()
    return alerts


def parse_args(message):
    splitted = message.text.split()
    return splitted[1:]


@dp.message_handler(commands=['start', 'help'])
async def send_welcome(message: types.Message):
    """
    This handler will be called when user sends `/start` or `/help` command
    """
    await message.reply('''‼️‼️ Привет! ‼️‼️\n
Я мониторю указанные тобой веб страницы на наличие/отсутствие указанных тобой кусков HTML.
Например, шаблоном может быть специфический серый цвет кнопки "Купить" на твоем любимом сайте, для продукта, которого в текущий момент нет в наличии.
(Если ты не знаком с HTML - просто тыкни правой кнопкой мыши по объекту в браузере, который хочешь отслеживать и нажми Inspect element source code, там будут какие-либо специфичные характеристики объекта)
У созданных мониторингов есть несколько статусов: ✅TEMPLATE_FOUND✅, 🚫TEMPLATE_NOT_FOUND🚫, 🛠HTTP_ERROR🛠.
Ты будешь тут же уведомлен (макс. 5 секунд задержки) о смене статуса во всех случаях, кроме переходов в HTTP_ERROR (Любой сайт иногда не отвечает на долю запросов) - подробную информацию об ошибках ты можешь посмотреть командой /status.

Примеры:
 Добавление мониторинга:   /add AlertName https://www.alert-example-shop.ru/ http_template
 Удаление   мониторинга:   /delete AlertName
 Текущий статус системы:   /status
 Помощь                :   /help

Надеюсь бот будет тебе полезен!''')


@dp.message_handler(commands=['status'])
async def send_status(message: types.Message):
    """
    This handler will be called when user sends `/start` or `/help` command
    """
    st = await status(message.chat.id)
    html = 'Работаем💪💪 Текущая максимальная задержка: {} секунд\n\nТвои мониторинги:\n\n'.format(update_time + 5)
    html += '<pre>\n| ' + ' | '.join(['Статус','Название','Адрес','Шаблон','Последняя ошибка']) + ' |\n'
    for row in st:
        html += '| ' + ' | '.join([str(i) for i in row]) + ' |\n'
    html += '</pre>'
    await message.reply(html, parse_mode='HTML')


@dp.message_handler(commands=['add'])
async def add_alert(message: types.Message):
    n_in_use = len(await status(message.chat.id))
    last_pay = await get_payment_ts(message.chat.id)
    if int(time.time()) - last_pay >= 30 * 24 * 60 * 60 and n_in_use >= 2:
        await message.reply("Нельзя создать больше алертов на бесплатной версии.\nПерейдите на платную версию всего за 100р и создавайте неограниченное количество мониторингов: /buy")
        return
    """
    This handler will be called when user sends `/start` or `/help` command
    """

    args = parse_args(message)
    try:
        assert len(args) == 3
        assert len(args[0]) < 200
        assert len(args[1]) < 200
        assert len(args[2]) < 200
        assert args[1].startswith('http')
    except:
        await message.reply("Неопознанные звери в аргументах.\nВаша команда должна иметь формат:\n\n/add alert_name http_address http_template")
        return

    await add(message.chat.id, *args)

    await message.reply("Успех.")


@dp.message_handler(commands=['delete'])
async def delete_alert(message: types.Message):
    """
    This handler will be called when user sends `/start` or `/help` command
    """
    args = parse_args(message)
    try:
        assert len(args) == 1
        assert len(args[0]) < 200
    except:
        await message.reply("Неопознанные звери в аргументах.\nВаша команда должна иметь формат:\n\n/delete alert_name")
        return

    await delete(message.chat.id, *args)
    await message.reply("Успех.")


@dp.message_handler(commands=['buy'])
async def cmd_buy(message: types.Message):
    await bot.send_invoice(message.chat.id, title='Продление подписки на месяц',
                           description='Купите подписку и получите возможность создавать неограниченное количество мониторингов',
                           provider_token=PAYMENTS_PROVIDER_TOKEN,
                           currency='rub',
                           is_flexible=False,  # True If you need to set up Shipping Fee
                           prices=prices,
                           start_parameter='time-machine-example',
                           payload='{}'.format(message.chat.id))


@dp.pre_checkout_query_handler(lambda query: True)
async def checkout(pre_checkout_query: types.PreCheckoutQuery):
    await bot.answer_pre_checkout_query(pre_checkout_query.id, ok=True,
                                        error_message="Aliens tried to steal your card's CVV,"
                                                      " but we successfully protected your credentials,"
                                                      " try to pay again in a few minutes, we need a small rest.")


@dp.message_handler(content_types=ContentTypes.SUCCESSFUL_PAYMENT)
async def got_payment(message: types.Message):
    await add_payment(message.chat.id)
    await bot.send_message(message.chat.id,
                           'Платеж прошел успешно! Теперь вы можете создавать до сотни мониторингов.',
                           parse_mode='Markdown')


if __name__ == '__main__':
    executor.start_polling(dp, skip_updates=True, on_startup=on_startup)