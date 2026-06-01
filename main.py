import os
import subprocess
from fastapi import FastAPI, UploadFile, File
from fastapi.middleware.cors import CORSMiddleware
import google.generativeai as genai

app = FastAPI()

# Enable CORS link so your Vercel frontend can talk to Render securely
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Initialize Google Gemini Configuration
genai.configure(api_key=os.environ.get("GEMINI_API_KEY"))

@app.post("/search-movie")
async def search_movie(file: UploadFile = File(...)):
    input_path = f"temp_{file.filename}"
    output_path = "optimized_pro_clip.mp4"
    
    try:
        # 1. Save incoming user video file locally
        with open(input_path, "wb") as f:
            f.write(await file.read())
            
        # 2. FFmpeg Grinder: 
        #    -t 15 -> Captures a full 15 seconds of context
        #    -an   -> STRIPS AUDIO completely (keeps filters from breaking the search)
        #    scale -> Keeps resolution low (360p) to preserve token budget
        ffmpeg_cmd = [
            "ffmpeg", "-y", "-i", input_path,
            "-ss", "00:00:00", "-t", "15",
            "-an",
            "-vf", "scale=-2:360",
            "-c:v", "libx264", "-crf", "30", "-preset", "ultrafast",
            output_path
        ]
        subprocess.run(ffmpeg_cmd, check=True)
        
        # 3. Upload the optimized 15-second clip to Gemini Cloud Storage
        sample_file = genai.upload_file(path=output_path, mime_type="video/mp4")
        
        # 4. Prompt the Lite model to look past editing distortions
        model = genai.GenerativeModel("gemini-2.5-flash-lite")
        prompt = (
            "Analyze the visual frames of this 15-second video clip. "
            "Identify the exact movie or cinematic show title it originates from. "
            "Ignore any editing visual distortions, color grading filters, or text subtitles. "
            "Respond ONLY with the name of the movie. If you are absolutely unable to identify it, reply with 'None'."
        )
        
        response = model.generate_content([sample_file, prompt])
        
        # 5. Instantly clean up cloud and local storage files
        genai.delete_file(sample_file.name)
        if os.path.exists(input_path): os.remove(input_path)
        if os.path.exists(output_path): os.remove(output_path)
        
        # Clean response interpretation
        cleaned_result = response.text.strip()
        if "None" in cleaned_result or not cleaned_result:
            return {"movie": None}
            
        return {"movie": cleaned_result}
        
    except Exception as e:
        # Clean up files if an processing error occurs
        if os.path.exists(input_path): os.remove(input_path)
        if os.path.exists(output_path): os.remove(output_path)
        return {"error": f"Analysis failed: {str(e)}"}
