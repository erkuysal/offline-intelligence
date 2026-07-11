from sqlalchemy.orm import Session

from app.models.conversation import Conversation, ConversationMessage, ConversationSource
from app.schemas.chat import ChatCompletionRequest, ChatSource


def get_or_create_conversation(
    db: Session,
    *,
    owner_id: int,
    conversation_id: int | None,
    title_seed: str,
) -> Conversation:
    if conversation_id is not None:
        conversation = db.get(Conversation, conversation_id)
        if conversation is None or conversation.owner_id != owner_id:
            raise ValueError("Conversation not found")
        return conversation

    conversation = Conversation(owner_id=owner_id, title=title_seed[:255])
    db.add(conversation)
    db.commit()
    db.refresh(conversation)
    return conversation


def persist_chat_exchange(
    db: Session,
    *,
    owner_id: int,
    request: ChatCompletionRequest,
    assistant_content: str,
    sources: list[ChatSource],
) -> Conversation:
    user_content = latest_user_message(request)
    conversation = get_or_create_conversation(
        db,
        owner_id=owner_id,
        conversation_id=request.conversation_id,
        title_seed=user_content,
    )
    db.add(ConversationMessage(conversation_id=conversation.id, role="user", content=user_content))
    assistant_message = ConversationMessage(
        conversation_id=conversation.id,
        role="assistant",
        content=assistant_content,
    )
    db.add(assistant_message)
    db.flush()
    for source in sources:
        db.add(
            ConversationSource(
                message_id=assistant_message.id,
                document_id=source.document_id,
                document_filename=source.document_filename,
                chunk_id=source.chunk_id,
                chunk_index=source.chunk_index,
                source_page=source.source_page,
                source_label=source.source_label,
                score=source.score,
            )
        )
    db.commit()
    db.refresh(conversation)
    return conversation


def latest_user_message(request: ChatCompletionRequest) -> str:
    return next(
        (message.content for message in reversed(request.messages) if message.role == "user"),
        request.messages[-1].content,
    )
