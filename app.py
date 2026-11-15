import os
import uvicorn
import gradio as gr
from server import app as fastapi_app

# Create a clean info interface for the root/Gradio view
with gr.Blocks(title="PlateTrack AI - Backend Engine") as demo:
    gr.Markdown("""
    # 🚘 PlateTrack AI - ANPR & Stay Monitoring API
    **Status**: 🟢 Active & Ready
    
    This Hugging Face Space hosts the high-performance YOLO11 + EasyOCR backend with 16 GB RAM.
    - **API Base**: `/`
    - **Stats Endpoint**: `/api/stats`
    - **Records Endpoint**: `/api/records`
    - **Scan Endpoint**: `/api/scan/base64`
    """)

# Mount Gradio onto the existing FastAPI server
app = gr.mount_gradio_app(fastapi_app, demo, path="/gradio-view")

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 7860))
    uvicorn.run(app, host="0.0.0.0", port=port)
