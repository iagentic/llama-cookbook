from fastapi import FastAPI
from webhook_main import app as webhook_app
from ec2_endpoints import app as ec2_app
from dotenv import load_dotenv

load_dotenv()

app = FastAPI(title="WhatsApp + Agent API", redirect_slashes=False)

# Mount both under separate prefixes
app.mount("/webhook", webhook_app)
app.mount("/agent", ec2_app)

# Health check
@app.get("/")
def root():
    return {"status": "ok", "message": "Combined API is running"}
