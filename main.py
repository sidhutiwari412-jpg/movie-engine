import os
import subprocess
import google.generativeai as genai
from fastapi import FastAPI, UploadFile, File, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from slowapi import Limiter
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware

# Initialize safety limiter (Max 12 requests per minute globally)
limiter = Limiter(key_func=get_remote_address, default_limits=["12/minute"])
app = FastAPI()
app.state.limiter = limiter
app.add_middleware(SlowAPIMiddleware)

# Allow your website frontend to communicate securely with this engine
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"], 
    allow_methods=["*"],
    allow_headers=["*"],
)

# Custom alert message if traffic crosses the 12 RPM safety window
@app.exception_handler(RateLimitExceeded)
async def custom_rate_limit_handler(request: Request, exc: RateLimitExceeded):
    return {"error": "Server busy processing other clips! Please wait a moment and try again."}

# Grab the secret key safely from cloud configuration settings
genai.configure(api_key=os.environ.get("GEMINI_API_KEY"))
model = genai.GenerativeModel("gemini-2.5-flash-lite")

@app.post("/search-movie")
async def search_movie(request: Request, file: UploadFile = File(...)):
    raw_path = f"raw_{file.filename}"
    clean_path = "processed_3sec.mp4"
    
    with open(raw_path, "wb") as buffer:
        buffer.write(await file.read())
        
    try:
        # Optimization command: Cut to 3 seconds, scale to 360p height, strip sound (-an)
        subprocess.run([
            "ffmpeg", "-y", "-i", raw_path,
            "-ss", "00:00:00", "-t", "3",
            "-vf", "scale=-2:360", "-vcodec", "libx264", "-crf", "30", "-an",
            clean_path
        ], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        
        # Send optimized file to Google File Cloud Manager
        media_file = genai.upload_file(path=clean_path)
        
        prompt = "Identify the movie or series title from this 3 second video edit. Output only the exact title name."
        
        # Set low-resolution processing mode to reduce token load by 97%
        config = genai.types.GenerationConfig(media_resolution="LOW")
        
        response = model.generate_content([media_file, prompt], generation_config=config)
        media_file.delete() 
        
        return {"movie": response.text.strip()}
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        # Clear files from storage disk to protect free server space
        if os.path.exists(raw_path): os.remove(raw_path)
        if os.path.exists(clean_path): os.remove(clean_path)
