import csv
import asyncio
import random
from collections import defaultdict
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, ContextTypes

# === Sozlamalar ===
CSV_FILE = "ITT_Quizizz_Import.csv"
TIME_LIMIT = 20        # Har bir savol uchun vaqt (soniya)
MAX_QUESTIONS = 25     # Testdagi savollar soni
PAUSE_AFTER_RESULT = 5 # Natija chiqqandan keyingi pauza

# === Savollarni yuklash ===
def load_questions(filename):
    questions = []
    with open(filename, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            q = {
                "question": row.get("Question") or "",
                "options": [
                    row.get("Option 1") or "",
                    row.get("Option 2") or "",
                    row.get("Option 3") or "",
                    row.get("Option 4") or "",
                ],
                "correct": row.get("Correct Answer") or "",
            }
            questions.append(q)
    return questions


QUESTIONS = load_questions(CSV_FILE)
CURRENT_INDEX = {}
SCORES = defaultdict(lambda: defaultdict(int))
ACTIVE = {}
STOPPED = set()  # To‘xtatilgan chatlar ro‘yxati


# === /start komandasi ===
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id

    # Agar test allaqachon boshlangan bo‘lsa
    if chat_id in ACTIVE:
        await update.message.reply_text("⚠️ Test allaqachon davom etmoqda. Agar to‘xtatmoqchi bo‘lsangiz /stop deb yozing.")
        return

    STOPPED.discard(chat_id)
    CURRENT_INDEX[chat_id] = 0
    SCORES[chat_id].clear()
    random.shuffle(QUESTIONS)

    await update.message.reply_text("🎯 Test boshlandi!")
    await send_question(context, chat_id)


# === /stop komandasi ===
async def stop(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    STOPPED.add(chat_id)
    ACTIVE.pop(chat_id, None)
    await update.message.reply_text("🛑 Test to‘xtatildi. Qayta boshlash uchun /restart deb yozing.")


# === /restart komandasi ===
async def restart(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    STOPPED.discard(chat_id)
    CURRENT_INDEX[chat_id] = 0
    SCORES[chat_id].clear()
    ACTIVE.pop(chat_id, None)
    random.shuffle(QUESTIONS)

    await update.message.reply_text("🔁 Test qayta boshlandi!")
    await send_question(context, chat_id)


# === Savol yuborish ===
async def send_question(context, chat_id):
    if chat_id in STOPPED:
        return

    idx = CURRENT_INDEX.get(chat_id, 0)
    if idx >= min(len(QUESTIONS), MAX_QUESTIONS):
        await show_results(context, chat_id)
        return

    q = QUESTIONS[idx]
    options = q["options"].copy()
    random.shuffle(options)

    buttons = [[InlineKeyboardButton(opt, callback_data=f"Q{idx}:{i}")] for i, opt in enumerate(options)]
    markup = InlineKeyboardMarkup(buttons)

    msg = await context.bot.send_message(
        chat_id=chat_id,
        text=f"❓ Savol {idx+1}/{MAX_QUESTIONS}\n\n{q['question']}\n\n⏳ {TIME_LIMIT} soniya qoldi.",
        reply_markup=markup,
    )

    ACTIVE[chat_id] = {
        "msg_id": msg.message_id,
        "q_index": idx,
        "options": options,
        "answers": {},
    }

    context.application.create_task(question_timer(context, chat_id, msg.message_id, TIME_LIMIT))


# === Tugma bosilganda ===
async def answer(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer("✅ Javob qabul qilindi!", show_alert=False)
    chat_id = query.message.chat.id
    user = query.from_user
    user_id = user.id
    user_name = user.first_name or "Foydalanuvchi"

    if chat_id in STOPPED:
        await query.answer("🛑 Test to‘xtatilgan.", show_alert=True)
        return

    data = query.data
    try:
        parts = data[1:].split(":")
        q_index = int(parts[0])
        opt_index = int(parts[1])
    except:
        return

    active = ACTIVE.get(chat_id)
    if not active or q_index != active["q_index"]:
        await query.answer("⏰ Bu savol allaqachon tugadi!", show_alert=True)
        return

    if user_id in active["answers"]:
        await query.answer("Siz allaqachon javob berdingiz!", show_alert=True)
        return

    options = active["options"]
    if opt_index >= len(options):
        return

    chosen_text = options[opt_index]
    active["answers"][user_id] = (user_name, chosen_text)


# === Timer (faqat to‘g‘ri javob chiqadi, uzun matn to‘liq ko‘rinadi) ===
async def question_timer(context, chat_id, message_id, seconds):
    for remaining in range(seconds - 1, 0, -2):
        await asyncio.sleep(2)
        if chat_id in STOPPED:
            return
        active = ACTIVE.get(chat_id)
        if not active or active["msg_id"] != message_id:
            return
        try:
            q = QUESTIONS[active["q_index"]]
            await context.bot.edit_message_text(
                chat_id=chat_id,
                message_id=message_id,
                text=f"❓ Savol {active['q_index']+1}/{MAX_QUESTIONS}\n\n"
                     f"{q['question']}\n\n⏳ {remaining} soniya qoldi.",
                reply_markup=InlineKeyboardMarkup(
                    [[InlineKeyboardButton(opt, callback_data=f"Q{active['q_index']}:{i}")]
                     for i, opt in enumerate(active["options"])]
                ),
            )
        except:
            pass

    if chat_id in STOPPED:
        return

    active = ACTIVE.get(chat_id)
    if not active or active["msg_id"] != message_id:
        return

    q = QUESTIONS[active["q_index"]]
    correct = q["correct"]

    result_text = f"⏰ *Vaqt tugadi!*\n\n✅ To‘g‘ri javob:\n\n*{correct}*"

    MAX_LEN = 4000
    if len(result_text) > MAX_LEN:
        parts = [result_text[i:i+MAX_LEN] for i in range(0, len(result_text), MAX_LEN)]
        for part in parts:
            await context.bot.send_message(chat_id=chat_id, text=part, parse_mode="Markdown")
    else:
        try:
            await context.bot.edit_message_text(
                chat_id=chat_id, message_id=message_id, text=result_text, parse_mode="Markdown"
            )
        except:
            await context.bot.send_message(chat_id=chat_id, text=result_text, parse_mode="Markdown")

    await asyncio.sleep(PAUSE_AFTER_RESULT)
    if chat_id in STOPPED:
        return

    ACTIVE.pop(chat_id, None)
    CURRENT_INDEX[chat_id] += 1
    await send_question(context, chat_id)


# === Yakuniy natija ===
async def show_results(context, chat_id):
    scores = SCORES.get(chat_id, {})
    if not scores:
        await context.bot.send_message(chat_id=chat_id, text="Hech kim to‘g‘ri javob bermadi.")
        return

    sorted_scores = sorted(scores.items(), key=lambda x: x[1], reverse=True)
    text = "🏁 *Test tugadi!*\n\n🏆 *Reyting:*\n"
    for i, (uid, score) in enumerate(sorted_scores, start=1):
        try:
            user = await context.bot.get_chat(uid)
            name = user.first_name or str(uid)
        except:
            name = str(uid)
        medal = "🥇" if i == 1 else "🥈" if i == 2 else "🥉" if i == 3 else "🎯"
        text += f"{medal} {i}. {name} — {score} ball\n"

    await context.bot.send_message(chat_id=chat_id, text=text, parse_mode="Markdown")


# === Asosiy ===
def main():
    TOKEN = "8002977056:AAE1nQ6hLk6APmYI9bUhRaSlgaxFivE2CWQ"
    app = Application.builder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("stop", stop))
    app.add_handler(CommandHandler("restart", restart))
    app.add_handler(CallbackQueryHandler(answer))
    app.run_polling()


if __name__ == "__main__":
    main()

