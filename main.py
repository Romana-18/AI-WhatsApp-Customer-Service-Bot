from fastapi import FastAPI
from pydantic import BaseModel
from database import SessionLocal, init_db, Customer, Conversation, Message
from ai import ask_ai

app = FastAPI()

init_db()


class WebhookMessage(BaseModel):
    message: str
    phone: str = "test-user"
    name: str | None = None
    company: str | None = None


@app.get("/")
def home():
    return {"message": "KAALEX WhatsApp Bot is running!"}


def get_or_create_customer(db, data):
    customer = db.query(Customer).filter(
        Customer.phone == data.phone
    ).first()

    if not customer:
        customer = Customer(
            phone=data.phone,
            name=data.name,
            company=data.company
        )
        db.add(customer)
        db.commit()
        db.refresh(customer)

    return customer


def get_or_create_conversation(db, customer_id):
    conversation = db.query(Conversation).filter(
        Conversation.customer_id == customer_id,
        Conversation.state.notin_(["confirmed", "cancelled"])
    ).order_by(Conversation.id.desc()).first()

    if not conversation:
        conversation = Conversation(
            customer_id=customer_id,
            state="active"
        )
        db.add(conversation)
        db.commit()
        db.refresh(conversation)

    return conversation


def get_conversation_history(db, conversation_id):
    messages = db.query(Message).filter(
        Message.conversation_id == conversation_id
    ).order_by(Message.id.asc()).all()

    return [
        {
            "sender": message.sender,
            "content": message.content
        }
        for message in messages
    ]


@app.post("/webhook")
async def webhook(data: WebhookMessage):

    db = SessionLocal()

    try:
        # 1. Get or create customer
        customer = get_or_create_customer(db, data)

        # 2. Get or create conversation
        conversation = get_or_create_conversation(
            db,
            customer.id
        )

        # 3. Save customer message
        customer_message = Message(
            conversation_id=conversation.id,
            sender="customer",
            content=data.message
        )

        db.add(customer_message)
        db.commit()

        # 4. Get conversation history
        history = get_conversation_history(
            db,
            conversation.id
        )

        # 5. Build context for AI
        context = "\n".join(
            f"{msg['sender']}: {msg['content']}"
            for msg in history
        )

        ai_input = f"""
Previous conversation:
{context}

Latest customer message:
{data.message}
"""

        # 6. Ask AI
        result = ask_ai(ai_input)

        reply = result["reply"]
        intent = result["intent"]
        needs_human = result["needs_human"]
        needs_confirmation = result["needs_confirmation"]

        # 7. Update conversation state

        if needs_human:
            conversation.state = "waiting_human"

        elif needs_confirmation:
            conversation.state = "waiting_confirmation"

        else:
            conversation.state = "active"

        if intent == "agreement":
            conversation.agreement_status = "pending"

        elif intent == "confirmation":
            conversation.agreement_status = "confirmed"
            conversation.state = "confirmed"

        elif intent == "cancellation":
            conversation.agreement_status = "cancelled"
            conversation.state = "cancelled"

        # 8. Save AI response
        bot_message = Message(
            conversation_id=conversation.id,
            sender="bot",
            content=reply
        )

        db.add(bot_message)
        db.commit()

        print("Customer:", data.message)
        print("AI:", reply)
        print("Intent:", intent)
        print("Needs Human:", needs_human)
        print("Conversation State:", conversation.state)

        return {
            "status": "success",
            "reply": reply,
            "intent": intent,
            "needs_human": needs_human,
            "needs_confirmation": needs_confirmation,
            "conversation_state": conversation.state
        }

    finally:
        db.close()