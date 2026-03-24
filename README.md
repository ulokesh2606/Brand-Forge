<div align="center">
  <img src="https://raw.githubusercontent.com/lokesh/brandforge/main/assets/brandforge_logo.png" alt="BrandForge Logo" width="120" />
</div>

<h1 align="center">BrandForge</h1>

<p align="center">
  <strong>An autonomous, multi-agent marketing content engine with Human-in-the-Loop (HITL) steering.</strong>
</p>

<p align="center">
  <img src="https://img.shields.io/badge/Python-3.10%2B-blue?style=flat-square&logo=python" alt="Python Version" />
  <img src="https://img.shields.io/badge/FastAPI-0.104.0%2B-009688?style=flat-square&logo=fastapi" alt="FastAPI" />
  <img src="https://img.shields.io/badge/LangGraph-0.0.26%2B-green?style=flat-square" alt="LangGraph" />
  <img src="https://img.shields.io/badge/Qdrant-Vector%20DB-db2777?style=flat-square&logo=qdrant" alt="Qdrant" />
  <img src="https://img.shields.io/badge/OpenAI-GPT--4o--mini-black?style=flat-square&logo=openai" alt="OpenAI" />
</p>

---

**BrandForge** isn't just a wrapper around ChatGPT. It’s an engineered **LangGraph State Machine** that autonomously crawls a brand's website, builds a localized Retrieval-Augmented Generation (RAG) vector space, and deploys a strict 4-agent assembly line to generate, evaluate, and iteratively refine marketing copy natively formatted for LinkedIn, Instagram, YouTube, and Google Ads.

Everything culminates in a **granular Expert Review Panel** where humans act as the final gatekeepers—approving flawless channels and sending structured revision directives back into the agentic loop.

---

## 🚀 Key Features

*   **⚡ Async Web Crawling**: Driven by `crawl4ai` to cleanly extract markdown context directly from the brand’s domain.
*   **🧠 Intelligent Memory (RAG)**: Automatically chunks and indexes crawled rules into an in-memory **Qdrant** Vector DB via OpenAI `text-embedding-3-small`.
*   **🤖 4-Agent LangGraph Pipeline**:
    *   **1. Interpreter**: Establishes the Brand Bible (Voice, Pillars, Forbidden Phrasing).
    *   **2. Strategist**: Formulates hooks and angles natively optimized for each requested channel.
    *   **3. Writer**: Generates the exact marketing draft.
    *   **4. Evaluator**: A strict AI QA node that forcibly fails and reprioritizes content if rules are broken (up to 3 iterative loops).
*   **🧑‍🏫 Human-in-the-loop (HITL)**: An interactive frontend interface deployed at the end of the AI pipeline. Users can structurally lock ("Approve") specific channels and surgically reject others with explicit rewriting directives.
*   **🌊 Server-Sent Events (SSE)**: Silky smooth, real-time UI streaming built entirely in Vanilla JS via FastAPI async generators.

---

## 🗺️ Architecture

For a detailed view of the node connections, conditional router logic, and exact data flow between the AI Evaluator and the HITL frontend, please see our dedicated [Architecture Documentation](ARCHITECTURE.md).

---

## 🛠️ Quick Start Guide

### 1. Prerequisites
- **Python 3.10+** minimum.
- A valid **OpenAI API Key**.

### 2. Installation
Clone the repository, initialize your virtual environment, and install all modular dependencies:

```bash
git clone https://github.com/yourusername/brandforge.git
cd brandforge
python -m venv venv

# Windows
.\venv\Scripts\activate
# Mac / Linux
source venv/bin/activate

pip install -r requirements.txt
```

> **Note:** The very first time you run this, you must initialize the playwright browser dependency for the web scraper:
> ```bash
> crawl4ai-setup
> ```

### 3. Environment Context
Ensure your `.env` file is initialized within the root directory:

```bash
echo "OPENAI_API_KEY=sk-your-openai-key-here" > .env
```

### 4. Running the Application Engine

Boot up the core FastAPI server (which natively serves the integrated HTML/JS/CSS frontend client):

```bash
uvicorn main:app --reload
```

Then simply open your browser to: **[http://localhost:8000](http://localhost:8000)**. 
*Looking to hit the endpoints headless? Auto-generated Swagger documentation sits at `/docs`.*

---

## ⚙️ How the HITL Feedback Loop Operates

One of BrandForge's unique signatures is the **Channel-locking HitL Engine**:
1. When Generation finishes, a `dict` mapping of all channels is sent over SSE to the frontend `RESULTS` screen.
2. The UI renders dedicated **Approve** and **Revision** input fields strictly partitioned by channel.
3. Upon submitting, the Web Client compiles a robust JSON payload tracking lock-states: `{"approved": ["linkedin"], "feedback": {"youtube": "Make this slightly more aggressive."}}`.
4. State Checkpointing using LangGraph's `MemorySaver` restores the graph instantly.
5. **Agent 3 (Writer)** parses the JSON, completely skips OpenAI invocation for locked "Approved" channels (preserving identical state), and hyper-focuses on the "Review" keys using the user's explicit directive natively injected back into the System Prompt!

## ☁️ Deployment (Render)

BrandForge is fully configured to be securely hosted on services like [Render](https://render.com).

### Step-by-Step Render Setup:
1. Create a `New Web Service` on Render and connect this exact GitHub repository.
2. Setup parameters:
   - **Environment:** `Python 3`
   - **Build Command:** `./render-build.sh` (or `pip install -r requirements.txt && playwright install chromium`)
   - **Start Command:** `uvicorn main:app --host 0.0.0.0 --port $PORT`
3. **Environment Variables**: You MUST provide your OpenAI key.
   - Click "Advanced" -> "Add Environment Variable"
   - Key: `OPENAI_API_KEY` | Value: `sk-your-key-here`
4. Click **Create Web Service**. Render will securely clone, build the Chromium engines for Crawl4AI, and host your live link! You can then send this live URL to anyone in the world to test your HITL pipeline.

---

## 🚀 Future Scope & Scale

This architecture is rigorously modular and built to scale into a robust Enterprise tool. Potential future additions:

1. **Persistent State Storage (PostgreSQL)**
   Currently, we use LangGraph's in-memory `MemorySaver()` for our Checkpointer and a dictionary for Qdrant. By swapping this to `SqliteSaver` or `PostgresSaver`, and migrating Qdrant to a cloud cluster, BrandForge could effortlessly store all generated drafts locally. You could add a "Dashboard" page showing previous content generations per brand!
2. **Multi-Tenant Architecture**
   For agency use, you could generate unique `thread_id` queues securely tied to specific logged-in user accounts or Stripe subscriptions, keeping every client's Qdrant vector space structurally isolated.
3. **Text-to-Video API Integrations**
   Because we statically separate and target channels like `YouTube` and `Instagram`, a distinct future iteration could plug our finalized JSON text drafts directly into APIs like **HeyGen** or **OpenAI Sora**, auto-generating a visual advertisement dynamically from the approved textual hook hook without manual video editing.
4. **Third-Party Publishing Integrations (Zapier/OAuth)**
   Instead of just "Approving and Saving" computationally, the API could trigger an OAuth integration to natively post the finalized LinkedIn draft to the user's actual profile upon approval!

---

## 📄 License
This architecture is licensed under the MIT License. Feel free to fork, expand, and commercialize.
