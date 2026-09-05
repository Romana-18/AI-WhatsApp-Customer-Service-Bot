import os
import requests
from dotenv import load_dotenv

load_dotenv()

api_key = os.getenv("OPENROUTER_API_KEY")

headers = {
    "Authorization": f"Bearer {api_key}",
    "Content-Type": "application/json",
}

payload = {
    "model": "minimax/minimax-m3:free",
    "messages": [
        {
            "role": "system",
            "content": """
أنت موظف خدمة عملاء لشركة Kalax، وهي شركة برمجيات.
رد بشكل محترم وطبيعي ومختصر.
يمكنك التحدث بالعربية والإنجليزية.
لا تخترع أسعارًا أو معلومات غير معروفة.
إذا لم تعرف الإجابة، قل إن أحد أعضاء الفريق يمكنه المساعدة.
"""
        },
        {
            "role": "user",
            "content": "أهلا، ممكن تعرفني خدماتكم؟"
        }
    ]
}

response = requests.post(
    "https://openrouter.ai/api/v1/chat/completions",
    headers=headers,
    json=payload,
)

print("Status:", response.status_code)

if response.ok:
    data = response.json()
    print("Model:", data.get("model"))
    print("Reply:", data["choices"][0]["message"]["content"])
else:
    print(response.text)