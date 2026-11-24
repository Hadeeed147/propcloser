"""Fixed replies for actions the lead has just confirmed, in English and Roman Urdu. No model call: instant, consistent, free."""
import re

URDU = {"hai", "hain", "mein", "mujhe", "chahiye", "chahie", "ka", "ki", "ke", "kar", "karo", "karna", "dein", "den", "haan",
        "han", "nahi", "ghar", "kitna", "kitne", "kya", "acha", "theek", "thik", "ji", "jee", "aur", "wala", "kal", "batao",
        "dikhao", "dekhna", "bilkul", "shukriya", "salam", "se", "ko", "baje"}

TEXT = {
    "booked": ("Done! I've booked your visit to {what}. See you there!",
               "Ho gaya! {what} ka visit book ho gaya hai. Wahan milte hain!"),
    "moved": ("Done! Your visit has been moved to {what}.", "Ho gaya! Aap ka visit ab {what} ke liye hai."),
    "cancelled": ("Done. Your visit to {what} is cancelled. Want to look at other options?",
                  "Theek hai, {what} ka visit cancel ho gaya hai. Kya aur options dekhna chahenge?"),
    "taken": ("Sorry, that slot was just taken, so nothing was booked. Free times: {what}. Which one suits you?",
              "Maazrat, yeh time abhi kisi aur ne le liya, kuch book nahi hua. Khali times: {what}. Kaunsa theek hai?"),
    "gone": ("I couldn't find that visit any more, so nothing changed.", "Woh visit ab maujood nahi, kuch tabdeel nahi hua."),
    "forgotten": ("Done. I've deleted what I had saved about you and our chat history. Booked visits stay until you cancel them.",
                  "Ho gaya. Aap ki saved maloomat aur chat history delete kar di hai. Booked visits cancel karne tak rahenge."),
}


def speaks_roman_urdu(texts: list[str]) -> bool:
    words = [w for t in texts for w in re.findall(r"[a-z]+", t.lower())]
    return sum(w in URDU for w in words) >= 2


def reply_for(key: str, what: str, recent_user_texts: list[str]) -> str:
    return TEXT[key][1 if speaks_roman_urdu(recent_user_texts) else 0].format(what=what)
