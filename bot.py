"""
This is a echo bot.
It echoes any incoming text messages.
"""

import asyncio
import logging
import aiosqlite
import sqlite3
import httpx
import pprint
import time

from aiogram import Bot, Dispatcher, executor, types

API_TOKEN = '1701420953:AAGkMe0awY4cbqtox4bBkIUO2TH53im-5wQ'

# Configure logging
logging.basicConfig(level=logging.INFO)

# Initialize bot and dispatcher
bot = Bot(token=API_TOKEN)
dp = Dispatcher(bot)
DB_NAME = 'db.sqlite'

update_time = 0

async def update_status(alert, status, chat_id, error=None):
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute('''UPDATE ALERTS SET status=? WHERE id=?''',
                         [status, alert[0], ])
        if error:
            await db.execute('''UPDATE ALERTS SET latest_error=? WHERE id=?''',
                             [str(error).replace('\n', ' '), alert[0], ])
        await db.commit()
    if alert[5] != status and 'HTTP_ERROR' not in status and 'HTTP_ERROR' not in alert[5]:
        await bot.send_message(chat_id, '‼️‼️‼️ Alert {} changed status to {}'.format(alert[2], status))


async def update_alerts():
    global update_time
    t1 = time.time()
    client = httpx.AsyncClient()
    async with aiosqlite.connect(DB_NAME) as db:
        cur = await db.execute('''SELECT id, chat_id, name, address, template, status FROM ALERTS''')
        alerts = await cur.fetchall()
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
    with sqlite3.connect(DB_NAME) as db:
        cur = db.cursor()

        cur.execute('''CREATE TABLE IF NOT EXISTS ALERTS(
                    id INTEGER PRIMARY KEY,
                    chat_id INTEGER,
                    name TEXT,
                    address TEXT,
                    template INTEGER,
                    status TEXT,
                    latest_error TEXT
                    )''')
    asyncio.create_task(updater())


async def add(chat_id, name, address, template):
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute('''INSERT INTO ALERTS(chat_id, name, address, template, status)
                         VALUES(?,?,?,?,?)''',
                         [chat_id, name, address, template, '⏳NS⏳'])
        await db.commit()


async def delete(chat_id, name):
    async with aiosqlite.connect(DB_NAME) as db:
        comm = await db.execute('''DELETE FROM ALERTS WHERE chat_id=? AND name=?''',
                         [chat_id, name])
        await db.commit()


async def status(chat_id):
    async with aiosqlite.connect(DB_NAME) as db:
        cur = await db.execute('''SELECT status, name, address, template, latest_error FROM ALERTS WHERE chat_id=?''',
                         [chat_id, ])
        alerts = await cur.fetchall()

    return alerts


def parse_args(message):
    splitted = message.text.split()
    return splitted[1:]


@dp.message_handler(commands=['start', 'help'])
async def send_welcome(message: types.Message):
    """
    This handler will be called when user sends `/start` or `/help` command
    """
    await message.reply('''‼️‼️ Make some alerts! ‼️‼️\n
Hi! I'm making alerts every 5 seconds to spectate your sites.
You just need to find a template for the http response text match:
For example, your template might be "Buy" for your favourite shop's web page.
Alerts has some statuses: TEMPLATE_FOUND, TEMPLATE_NOT_FOUND, HTTP_ERROR.
If the status is changing, you will be notified fast. Be aware, you will not be notificated about HTTP_ERROR status - it might be flapping over time
        Command examples:
        /add AlertName https://www.alert-example-shop.ru/ http_template
        /delete AlertName
        /status
        /help

Try it out!''')


@dp.message_handler(commands=['status'])
async def send_status(message: types.Message):
    """
    This handler will be called when user sends `/start` or `/help` command
    """
    st = await status(message.chat.id)
    html = 'Bot is working! Latest check period: {}\n\nYOUR ALERTS:\n\n'.format(update_time + 5)
    html += '<pre>\n| ' + ' | '.join(['Status','Name','Url','Template','LatestError']) + ' |\n'
    for row in st:
        html += '| ' + ' | '.join([str(i) for i in row]) + ' |\n'
    html += '</pre>'
    await message.reply(html, parse_mode='HTML')


@dp.message_handler(commands=['add'])
async def add_alert(message: types.Message):
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
        await message.reply("Cant parse args.\nYour command must be in format:\n\n/add alert_name http_address http_template")
        return

    await add(message.chat.id, *args)

    await message.reply("Success.")


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
        await message.reply("Cant parse args.\nYour command must be in format:\n\n/delete alert_name")
        return

    await delete(message.chat.id, *args)
    await message.reply("Success.")


if __name__ == '__main__':
    executor.start_polling(dp, skip_updates=True, on_startup=on_startup)