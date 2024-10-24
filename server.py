import requests
from fastapi import FastAPI, Request
from fastapi.responses import StreamingResponse
import json
import os
from pyngrok import ngrok  # Import ngrok for tunneling

app = FastAPI()

# This will store all requests and responses locally
def store_locally(data, file_name):
    with open(file_name, 'a') as f:
        f.write(json.dumps(data) + "\n")

@app.post("/api/v1/chat/completions")
async def proxy_to_openrouter(request: Request):
    # Read incoming request body
    body = await request.json()

    # Store the request locally
    store_locally(body, "local_requests.json")

    # Define the headers and send the request to OpenRouter
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {os.getenv('OPENROUTER_API_KEY')}",
    }

    # Forward the request to OpenRouter with streaming enabled
    response = requests.post(
        "https://openrouter.ai/api/v1/chat/completions", 
        headers=headers, 
        json=body, 
        stream=True
    )

    # Store response locally as it comes
    def response_stream():
        for chunk in response.iter_content(chunk_size=1024):
            if chunk:
                store_locally(chunk.decode('utf-8'), "local_responses.json")
                yield chunk

    # Stream the response back to the client
    return StreamingResponse(response_stream(), media_type="application/json")



if __name__ == "__main__":
    # Start ngrok tunnel
    public_url = ngrok.connect("3000", "http")
    print(f"ngrok tunnel: {public_url}")

    # Run the FastAPI app on port 3000
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=3000)
