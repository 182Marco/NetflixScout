# 🎬 NetflixScout

### An AI Discovery Chatbox for Netflix Content Exploration

# 🚀 How to Run the Project

Before starting the application, you must download the dataset used by the RAG pipeline.

## 📥 Download the Dataset

Download the **CMU Movie Summary Corpus** from:

🔗 https://www.cs.cmu.edu/~ark/personas/

---

## 📂 Extract the Dataset

After downloading and extracting the archive, place the dataset inside the `datasets/` directory.

⚠️ Depending on how the archive is extracted, you may end up with a duplicated folder structure such as:

```text
datasets/
└── MovieSummaries/
    └── MovieSummaries/
        ├── character.metadata.tsv
        ├── movie.metadata.tsv
        ├── name.clusters.txt
        ├── plot_summaries.txt
        ├── README.txt
        └── tvtropes.clusters.txt
```

If this happens, move the files up one level and remove the extra `MovieSummaries` folder.

✅ The final structure **must** look exactly like this:

```text
datasets/
└── MovieSummaries/
    ├── character.metadata.tsv
    ├── movie.metadata.tsv
    ├── name.clusters.txt
    ├── plot_summaries.txt
    ├── README.txt
    └── tvtropes.clusters.txt
```

---

## ✅ Verify the Installation

Make sure the following file exists:

```text
datasets/MovieSummaries/plot_summaries.txt
```

This file contains the movie plot summaries that will be processed, chunked, embedded, and indexed by the RAG pipeline.

Once the dataset has been placed in the correct location, you can proceed with the project setup and data ingestion steps.


## 🚀 Project Vision

**NetflixScout** is a Python-based intelligent discovery platform designed to help users find movies and TV series through natural conversation rather than traditional search filters.

Instead of manually browsing categories, users can describe concepts, themes, emotions, plot patterns, or analogies they have in mind.

Examples:

> "Show me movies that discuss loneliness and redemption in a single story."

> "Find TV series similar to *Dark* because of their philosophical themes rather than their sci-fi setting."

> "What productions have explored artificial intelligence as a moral dilemma?"

The system interprets the request, searches across multiple knowledge sources, and provides highly relevant recommendations together with a transparent explanation of how the result was generated.

---

# 🐍 Technology Stack

NetflixScout will be developed in **Python**, leveraging modern AI and data-access technologies to build a scalable and maintainable agentic architecture.

Potential technologies include:

- Python
- FastAPI
- LangChain / LangGraph
- Vector Databases
- SQL Databases
- OpenAI-compatible LLMs
- Embedding Models
- Retrieval Pipelines
- Observability & Monitoring Tools

The architecture is intentionally modular to support future extensions and integrations.

---

# 🧠 Core Concept

The user interacts with a conversational AI assistant instead of a traditional search engine.

The assistant can reason about:

- Themes
- Plot elements
- Narrative structures
- Character archetypes
- Genres
- Emotional tone
- Historical periods
- Direct and indirect similarities

This allows discovery through concepts instead of keywords.

---

# ⚙️ Agentic Architecture

The chatbox is powered by multiple agentic tools working together.

## 🥇 Primary Tool: RAG

### What does RAG mean?

**RAG = Retrieval Augmented Generation**

### What is it?

In simple terms:

A language model does not rely solely on its pre-trained knowledge.

Before generating a response, it searches a knowledge base containing information about movies, series, actors, plots, themes, reviews, metadata, and other relevant content.

The retrieved information is then used to generate a more accurate and grounded answer.

### Why is it important?

Without RAG:

- The model may hallucinate
- Information may be outdated
- Recommendations may be generic

With RAG:

- Answers are grounded on real data
- Recommendations become more accurate
- The reasoning process becomes explainable

---

## 🥈 Secondary Tool: Database Queries

The second most important capability is structured database access.

The system can query information such as:

- Titles
- Cast
- Directors
- Release dates
- Genres
- Runtime
- Ratings
- Platform metadata

This allows precise filtering and validation of the results identified by the retrieval system.

---

## 🧩 Additional Agentic Tools

The architecture is designed to be extensible.

Potential future tools include:

- Semantic Search
- Knowledge Graphs
- Recommendation Engines
- User Preference Profiles
- Trend Analysis Services
- External APIs
- Vector Databases
- Ranking and Scoring Engines

---

# 🔄 High-Level Retrieval Cycle

The platform will expose an explainable version of its retrieval and reasoning process.

The goal is to make the system understandable even to non-technical users.

---

## 1️⃣ User Request

The user starts with a natural language query.

Example:

> "Find stories that discuss free will and destiny in a psychological way."

---

## 2️⃣ Query Understanding

NetflixScout extracts:

- Themes
- Concepts
- User intent
- Constraints

---

## 3️⃣ Retrieval Phase

The RAG system searches the knowledge base and retrieves potentially relevant content.

### Retrieved Chunks

Information fragments that may be related to the user's request.

### Candidate Chunks

The most promising chunks selected for deeper evaluation.

---

## 4️⃣ Re-Ranking

Candidate chunks are evaluated and scored.

The most relevant information is promoted while less relevant content is discarded.

---

## 5️⃣ Top-K Selection

Only the highest-quality results are retained.

These are known as:

**Top-K Results**

The value of **K** may vary depending on the retrieval strategy and system configuration.

---

## 6️⃣ Database Interrogation

After retrieval, structured queries are executed against the database.

Examples:

- Movie metadata
- Series metadata
- Ratings
- Production information
- Availability details

---

## 7️⃣ Response Reasoning

The assistant combines:

- RAG outputs
- Retrieved chunks
- Database results
- Conversation history

to produce the final recommendation.

---

# 🔍 Explainability Output

Transparency is one of the key goals of NetflixScout.

Users and stakeholders will be able to inspect a simplified explanation of the entire retrieval and reasoning workflow.

The output may include:

- ✅ Reasoning steps
- ✅ Retrieved chunks
- ✅ Candidate chunks
- ✅ Re-ranking scores
- ✅ Top-K selection
- ✅ Database calls performed
- ✅ Database responses received
- ✅ Final reasoning process
- ✅ Final answer generation

This increases trust, observability, and debuggability while showcasing the work performed by the platform.

---

# 🧵 Conversation Memory

To provide coherent and personalized interactions, NetflixScout continuously leverages previous conversation context.

Benefits include:

- Follow-up questions
- Progressive refinement
- Consistent recommendations
- Better understanding of user preferences

---

## 📦 Context Compression

Keeping the entire conversation forever would become expensive and inefficient.

To solve this problem, NetflixScout applies context compression techniques.

### How?

Language models periodically generate compact summaries of previous exchanges.

These summaries preserve:

- User preferences
- Previously explored topics
- Important decisions
- Relevant constraints

while dramatically reducing token consumption.

---

## 🔎 Context Audit Trail

The explainability layer will also expose:

- Original context size
- Compressed context size
- Generated summaries
- Retrieved memory elements

This demonstrates how memory influenced each answer and helps validate system behavior.

---

# 🔐 Security & Governance

Security and operational governance are first-class requirements.

---

## 🛡️ Jailbreak Prevention

The chatbox will contain mechanisms to mitigate:

- Prompt Injection
- Jailbreak Attempts
- Instruction Override Attacks
- Out-of-Scope Requests

Users will only be allowed to access supported business functionalities.

---

## 🗄️ Database Protection

Database interactions will be strictly controlled.

Allowed operations:

```sql
SELECT
```

Blocked operations:

```sql
INSERT
UPDATE
DELETE
DROP
ALTER
TRUNCATE
```

This prevents accidental or malicious modifications to production data.

---

## 💰 Cost Control

NetflixScout will implement spending governance mechanisms such as:

- Request quotas
- Agent execution limits
- Token budgets
- Maximum retrieval depth
- Caching strategies
- Dynamic model selection

This ensures predictable operational costs and sustainable scalability.

---

# 📈 Scalability & Maintainability

NetflixScout is designed around modular and independently deployable components.

Benefits include:

- Independent tool evolution
- Easier testing
- Reduced coupling
- Improved observability
- Horizontal scalability
- Simplified maintenance
- Incremental feature adoption

Future agentic tools can be integrated without redesigning the overall architecture.

---

# 🏗️ Expected Benefits

✅ Better content discovery

✅ Natural language interaction

✅ Explainable recommendations

✅ Transparent reasoning process

✅ Conversation-aware responses

✅ Controlled operational costs

✅ Strong security posture

✅ Long-term maintainability

✅ Horizontal scalability

✅ Extensible agent ecosystem

---

# 🎯 Final Objective

The ultimate goal of **NetflixScout** is to create an intelligent movie and TV-show discovery assistant capable of understanding complex human intentions and transforming them into highly relevant recommendations.

By combining **Python**, **RAG**, **database querying**, **conversation memory**, **context compression**, **agentic reasoning**, and **transparent explainability**, NetflixScout aims to deliver a discovery experience that is significantly more powerful, trustworthy, maintainable, scalable, and user-friendly than traditional search and filtering systems.