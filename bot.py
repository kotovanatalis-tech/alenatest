"""
Telegram-бот «Готовы ли вы к международному собесу?»

• /start — приветствие + две кнопки: открыть Mini App или пройти тест прямо в чате
• Тест в чате — 9 вопросов, одно сообщение редактируется по ходу
• Результат — по тем же правилам, что и в веб-версии

Переменные окружения:
  BOT_TOKEN   — токен от @BotFather (обязательно)
  WEBAPP_URL  — https-адрес, где лежит webapp/index.html (необязательно)
  CTA_URL     — ссылка для кнопки «Собрать мою дорожную карту» (необязательно)
"""
import asyncio
import html
import logging
import os

from aiogram import Bot, Dispatcher, F
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.filters import Command, CommandStart
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    MenuButtonWebApp,
    Message,
    WebAppInfo,
)

from quiz_data import (
    BLOCKS, QUESTIONS, RESULTS, HEADER_TITLE, HEADER_ALL_OK, HEADER_SOME_WEAK,
    WHATS_NEXT, CTA_TEXT, CTA_BUTTON, evaluate,
)

BOT_TOKEN = os.getenv("BOT_TOKEN", "")
WEBAPP_URL = os.getenv("WEBAPP_URL", "").strip()
CTA_URL = os.getenv("CTA_URL", "").strip()

dp = Dispatcher()

# user_id -> список баллов по уже отвеченным вопросам
sessions: dict[int, list[int]] = {}

NUM = ["1️⃣", "2️⃣", "3️⃣"]
e = html.escape


# ---------- клавиатуры ----------

def start_keyboard() -> InlineKeyboardMarkup:
    rows = []
    if WEBAPP_URL:
        rows.append([InlineKeyboardButton(text="✨ Открыть тест-приложение",
                                          web_app=WebAppInfo(url=WEBAPP_URL))])
    rows.append([InlineKeyboardButton(text="💬 Пройти тест здесь, в чате", callback_data="go")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def question_keyboard(qi: int) -> InlineKeyboardMarkup:
    _, _, opts = QUESTIONS[qi]
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text=NUM[oi], callback_data=f"a:{qi}:{oi}")
        for oi in range(len(opts))
    ]])


def result_keyboard() -> InlineKeyboardMarkup:
    rows = []
    if CTA_URL:
        rows.append([InlineKeyboardButton(text=f"🚀 {CTA_BUTTON}", url=CTA_URL)])
    rows.append([InlineKeyboardButton(text="🔁 Пройти тест заново", callback_data="go")])
    if WEBAPP_URL:
        rows.append([InlineKeyboardButton(text="✨ Открыть приложение",
                                          web_app=WebAppInfo(url=WEBAPP_URL))])
    return InlineKeyboardMarkup(inline_keyboard=rows)


# ---------- тексты ----------

WELCOME = (
    "<b>Готовы ли вы к международному собесу?</b>\n\n"
    "9 вопросов — 3 минуты. В конце покажем твою точку А по трём зонам, "
    "от которых реально зависит собес:\n"
    + "\n".join(f"• {b}" for b in BLOCKS)
)


def progress(done: int) -> str:
    return "●" * done + "○" * (len(QUESTIONS) - done)


def question_text(qi: int) -> str:
    block, q, opts = QUESTIONS[qi]
    lines = [
        f"<i>Вопрос {qi + 1} из {len(QUESTIONS)} · {e(BLOCKS[block])}</i>",
        progress(qi),
        "",
        f"<b>{e(q)}</b>",
        "",
    ]
    lines += [f"{NUM[i]} {e(t)}" for i, (t, _) in enumerate(opts)]
    return "\n".join(lines)


def result_text(scores: list[int]) -> str:
    block_scores, weak, target = evaluate(scores)
    parts = [f"<b>{HEADER_TITLE}</b>",
             HEADER_SOME_WEAK if weak else HEADER_ALL_OK, ""]

    for i, r in enumerate(RESULTS):
        is_weak = i in weak
        pill = "🟠 <b>Подтянуть</b>" if is_weak else "🟢 <b>ОК</b>"
        parts.append(f"{pill} · <b>{e(r['title'])}</b>")
        parts.append(e(r["warn"] if is_weak else r["ok"]))
        if i == target:
            v = r["video"]
            parts.append(f"\n🎬 <b>Видео по твоей теме:</b> «{e(v['title'])}»\n<i>{e(v['desc'])}</i>")
        parts.append("")

    if not weak:
        parts += ["<b>Что дальше?</b>", e(WHATS_NEXT), ""]

    parts.append(f"💡 {e(CTA_TEXT)}")
    return "\n".join(parts)


# ---------- хендлеры ----------

@dp.message(CommandStart())
async def cmd_start(message: Message):
    await message.answer(WELCOME, reply_markup=start_keyboard())


@dp.message(Command("quiz"))
async def cmd_quiz(message: Message):
    sessions[message.from_user.id] = []
    await message.answer(question_text(0), reply_markup=question_keyboard(0))


@dp.callback_query(F.data == "go")
async def cb_go(call: CallbackQuery):
    sessions[call.from_user.id] = []
    await call.message.answer(question_text(0), reply_markup=question_keyboard(0))
    await call.answer()


@dp.callback_query(F.data.startswith("a:"))
async def cb_answer(call: CallbackQuery):
    _, qi_s, oi_s = call.data.split(":")
    qi, oi = int(qi_s), int(oi_s)
    answers = sessions.get(call.from_user.id)

    # защита от двойных нажатий и старых сообщений
    if answers is None or qi != len(answers):
        await call.answer("Этот вопрос уже позади — нажми /quiz, чтобы начать заново.")
        return

    _, _, opts = QUESTIONS[qi]
    answers.append(opts[oi][1])
    await call.answer()

    if len(answers) < len(QUESTIONS):
        nxt = len(answers)
        await call.message.edit_text(question_text(nxt), reply_markup=question_keyboard(nxt))
    else:
        await call.message.edit_text("✅ Готово! Считаю результат…")
        await call.message.answer(result_text(answers), reply_markup=result_keyboard())
        sessions.pop(call.from_user.id, None)


async def main():
    if not BOT_TOKEN:
        raise SystemExit("Укажи BOT_TOKEN в переменных окружения")
    logging.basicConfig(level=logging.INFO)
    bot = Bot(BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    if WEBAPP_URL:
        # кнопка слева от поля ввода, открывающая Mini App
        await bot.set_chat_menu_button(
            menu_button=MenuButtonWebApp(text="Тест", web_app=WebAppInfo(url=WEBAPP_URL)))
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
