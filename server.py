import json
import os
from fastapi import FastAPI, Request
from fastapi.responses import StreamingResponse
from pyngrok import ngrok
import httpx

app = FastAPI()


# Function to store data locally
def store_locally(data, file_name):
    with open(file_name, "a") as f:
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
        "Authorization": f"Bearer {os.getenv('OPENROUTER_API_KEY')}",
    }
    combined_data = {
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

                        # Process complete lines
                    # while "\n" in buffer:
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
                store_locally(combined_data, "combined_data.json")

    # Stream the response back to the client
    return StreamingResponse(response_stream(), media_type="text/event-stream")


if __name__ == "__main__":
    # Start ngrok tunnel
    public_url = ngrok.connect(8000)
    print(f"ngrok tunnel: {public_url}")

    # Run the FastAPI app on port 8000
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8000)
