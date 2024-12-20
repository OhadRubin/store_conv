import json
import os
from fastapi import FastAPI, Request
from fastapi.responses import StreamingResponse
from pyngrok import ngrok
import httpx
import datetime
from fastapi.middleware.cors import CORSMiddleware  # Add this import
from typing import List, Dict, Optional, Union
from pydantic import BaseModel
from datetime import datetime
import uuid

    

app = FastAPI()
OPENROUTER_API_KEY = os.getenv('OPENROUTER_API_KEY')

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Allows all origins
    allow_credentials=True,
    allow_methods=["*"],  # Allows all methods
    allow_headers=["*"],  # Allows all headers
)


class OpenAIMessage(BaseModel):
    role: str  # The role in the conversation, e.g., "system" or "user"
    content: str  # The message content


class Request(BaseModel):
    model: str  # Model identifier, e.g., "openai/gpt-4o"
    messages: List[OpenAIMessage]  # List of messages in the conversation
    temperature: Optional[float] = None  # Temperature setting for generation
    max_tokens: Optional[int] = None  # Maximum token limit for generation
    stream: Optional[bool] = None  # Whether the response is streamed


class ChatData(BaseModel):
    timestamp: str  # Timestamp of the interaction
    request: Request  # The request details
    response: str  # Response generated by the model


class WebUIMessage(BaseModel):
    id: str  # Unique ID of the message
    parentId: Optional[
        str
    ]  # ID of the parent message (or None if it's the first message)
    childrenIds: List[str]  # List of child message IDs
    role: str  # Role of the author, either 'user' or 'assistant'
    content: str  # Content of the message
    model: str = (
        "gpt-3.5-turbo"  # Model used for this message (default 'gpt-3.5-turbo')
    )
    done: bool = (
        True  # Indicates if the message generation is complete (always True here)
    )
    context: Optional[Union[dict, None]] = None  # Context data (currently None)


class History(BaseModel):
    currentId: str  # The ID of the last processed message
    messages: Dict[
        str, WebUIMessage
    ]  # Mapping of message IDs to `WebUIMessage` objects


class Chat(BaseModel):
    history: History  # History of messages in the conversation
    models: List[
        str
    ]  # List of models used in the conversation (e.g., ['gpt-3.5-turbo'])
    messages: List[WebUIMessage]  # List of messages in the conversation
    options: dict = {}  # Options object (currently empty)
    timestamp: str  # Timestamp of the conversation
    title: str = "New Chat"  # Title of the conversation


class ConvertedChat(BaseModel):
    id: str  # Unique conversation ID
    user_id: str  # User ID (always empty in this implementation)
    title: str = "New Chat"  # Title of the conversation
    chat: Chat  # The chat object containing history and message details
    timestamp: str  # Timestamp of the conversation


def convert_openai_messages(convo) -> Chat:
    messages = []
    current_id = ""
    message_map = {}

    # First message has no parent
    first_message = convo.request.messages[0]
    first_id = str(uuid.uuid4())
    first_message_obj = WebUIMessage(
        id=first_id,
        parentId=None,
        childrenIds=[],
        role=first_message.role,
        content=first_message.content,
        model=convo.request.model,
        done=True,
        context=None,
    )
    messages.append(first_message_obj)
    message_map[first_id] = first_message_obj
    last_id = first_id

    # Process subsequent messages
    for openai_message in convo.request.messages[1:]:
        message_id = str(uuid.uuid4())
        new_message = WebUIMessage(
            id=message_id,
            parentId=last_id,
            childrenIds=[],
            role=openai_message.role,
            content=openai_message.content,
            model=convo.request.model,
            done=True,
            context=None,
        )
        # Update parent's childrenIds
        message_map[last_id].childrenIds.append(message_id)
        messages.append(new_message)
        message_map[message_id] = new_message
        last_id = message_id

    # Add the response message
    response_id = str(uuid.uuid4())
    response_message = WebUIMessage(
        id=response_id,
        parentId=last_id,
        childrenIds=[],
        role="assistant",
        content=convo.response,
        model=convo.request.model,
        done=True,
        context=None,
    )
    # Update parent's childrenIds
    message_map[last_id].childrenIds.append(response_id)
    messages.append(response_message)
    message_map[response_id] = response_message
    current_id = response_id

    chat = Chat(
        history=History(currentId=current_id, messages=message_map),
        models=[convo.request.model],
        messages=messages,
        options={},
        timestamp=convo.timestamp,
    )
    return chat


def validate_chat(chat: Chat) -> bool:
    # Placeholder validation logic (define actual validation as needed)
    return bool(chat)


import json


def convert_file(file_path):

    dict_chats = []
    with open(file_path, "r") as f:
        for line in f:
            chat_data = json.loads(line.strip())
            chat = ChatData(**chat_data)
            try:
                chat = convert_openai_messages(chat).model_dump()
            except json.JSONDecodeError as e:
                print(e)
                continue
            dict_chats.append(chat)
    return dict_chats


import os


def import_chat(chat):
    import requests

    url = "http://localhost:8080/api/chats/new"
    headers = {
        "Authorization": f"Bearer {os.getenv('API_KEY')}",
        "Content-Type": "application/json",
    }
    payload = {
        "chat": chat,
    }

    response = requests.post(url, headers=headers, json=payload)
    if response.status_code == 200:
        print(f"Successfully imported chat (status code: {response.status_code})")
    else:
        print(f"Failed to import chat (status code: {response.status_code})")


# Function to handle chat storage (either locally or via API)
def store_chat(data, use_api=False):
    if use_api:
        chat = convert_openai_messages(ChatData(**data)).model_dump()
        import_chat(chat)
    else:
        # Original local storage logic
        now = datetime.datetime.now()
        month_dir = os.path.join("data", now.strftime("%Y-%m"))
        filename = f"{now.strftime('%Y-%m-%d')}.jsonl"
        os.makedirs(month_dir, exist_ok=True)
        file_path = os.path.join(month_dir, filename)
        with open(file_path, "a") as f:
            f.write(json.dumps(data) + "\n")


# Function to remove unneeded fields from response data
def remove_unneeded_fields(data):
    # Extract the 'content' from 'delta' in 'choices'
    content = []
    if "choices" in data:
        for choice in data["choices"]:
            if "delta" in choice and "content" in choice["delta"]:
                content.append(choice["delta"]["content"])
    return "".join(content)

@app.post("/api/v1/chat/completions")
async def proxy_to_openrouter(request: Request):
    use_api = os.getenv('USE_API_IMPORT', 'false').lower() == 'true'
    # Read incoming request body
    body = await request.json()

    # Instead of storing it now, we'll store it later together with the response
    request_data = body
    model_name = request_data["model"]
    if "cloood" in model_name:
        request_data["model"] = "anthropic/claude-3.5-sonnet:beta"

    # Define the headers
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {OPENROUTER_API_KEY}",
    }
    combined_data = {
        "timestamp": datetime.datetime.now().isoformat(),  # Add timestamp here
        "request": request_data,
    }
    # Define the async generator for streaming
    async def response_stream():
        # Create an async client
        async with httpx.AsyncClient() as client:
            # Forward the request to OpenRouter with streaming enabled
            async with client.stream(
                "POST",
                "https://openrouter.ai/api/v1/chat/completions",
                headers=headers,
                json=body,
            ) as response:
                # Collect processed response data
                response_content = ""
                buffer_list = []
                async for chunk in response.aiter_bytes():
                    if chunk:
                        # Yield the original chunk to the client
                        yield chunk

                        # Decode chunk and add to buffer
                        buffer_list.append(chunk.decode("utf-8"))
                buffer = "".join(buffer_list)

                lines = [line.strip() for line in buffer.split("\n")]
                lines = [line for line in lines if len(line)>0]
                for line in lines:
                    if line.startswith("data: "):
                        json_str = line[6:].strip()
                        try:
                            data = json.loads(json_str)
                            # Extract and accumulate the content
                            content_fragment = remove_unneeded_fields(data)
                            response_content += content_fragment
                        except json.JSONDecodeError:
                            pass  # Handle or log the error if needed

                if len(response_content)==0:
                    assert len(lines)==1
                    try:
                        data = json.loads(lines[0])
                        response_content = data["choices"][0]["message"]["content"]
                    except json.JSONDecodeError:
                        response_content = ""

                combined_data["response"] = response_content
                store_chat(combined_data, use_api=use_api)

    # Stream the response back to the client
    return StreamingResponse(response_stream(), media_type="text/event-stream")


@app.get("/api/v1/models")
async def proxy_models():
    headers = {
        "Authorization": f"Bearer {OPENROUTER_API_KEY}",
    }

    # Set a custom timeout and disable SSL verification
    timeout = httpx.Timeout(10.0)
    async with httpx.AsyncClient(timeout=timeout, verify=False) as client:
        response = await client.get(
            "https://openrouter.ai/api/v1/models", 
            headers=headers
        )
        return response.json()


if __name__ == "__main__":
    # Start ngrok tunnel
    public_url = ngrok.connect(8000).public_url
    print(f"ngrok tunnel: {public_url}/api/v1")

    # Run the FastAPI app on port 8000
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8000)
