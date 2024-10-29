import json
import os
from fastapi import FastAPI, Request
from fastapi.responses import StreamingResponse
from pyngrok import ngrok
import httpx
import datetime
from fastapi.middleware.cors import CORSMiddleware  # Add this import
from convert import convert_openai_messages, ChatData, import_chat


app = FastAPI()
OPENROUTER_API_KEY = os.getenv('OPENROUTER_API_KEY')

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Allows all origins
    allow_credentials=True,
    allow_methods=["*"],  # Allows all methods
    allow_headers=["*"],  # Allows all headers
)

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
    content = ""
    if "choices" in data:
        for choice in data["choices"]:
            if "delta" in choice and "content" in choice["delta"]:
                content += choice["delta"]["content"]
    return content


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
                buffer = ""
                async for chunk in response.aiter_bytes():
                    if chunk:
                        # Yield the original chunk to the client
                        yield chunk

                        # Decode chunk and add to buffer
                        chunk_str = chunk.decode("utf-8")
                        buffer += chunk_str

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
