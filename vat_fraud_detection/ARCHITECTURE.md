# System Architecture

## 1. Functional Architecture

High-level view of actors, systems, and their responsibilities.

```mermaid
graph TB
    subgraph EU_INST["🏛️ European Institution"]
        HUB["EU VAT Hub\n─────────────────\nCentral invoice repository\nfor all member states.\nStores factual data only:\nparties, amounts, VAT rates,\ntransaction classification.\nNo risk scoring."]
    end

    subgraph IE["🇮🇪 Irish Revenue"]
        APP["Ireland VAT App\n─────────────────\nCountry-level audit tool.\nMaintains local invoice DB\n(cutoff: 2026-03-25).\nFetches increment from Hub,\npre-classifies by risk,\nruns LLM compliance analysis."]
        LLM["LM Studio\n─────────────────\nLocal LLM server.\nVAT compliance verdicts\nper invoice line item,\nbacked by legislation RAG."]
    end

    AUDITOR(("👤 Irish\nAuditor"))
    EU_ADMIN(("👤 EU\nAdministrator"))

    AUDITOR -->|"Browse EU invoices\nFetch Irish increment\nQueue & analyse invoices\nReview verdicts & risk scores"| APP
    APP -->|"Query invoices\nFetch increment (IE, post-cutoff)"| HUB
    APP -->|"RAG + compliance analysis\nper line item"| LLM
    EU_ADMIN -->|"Monitor inbound requests\nBrowse all member-state data\nView analytics"| HUB
```

---

## 2. Technical Architecture

Detailed view of all components, scripts, databases and their interconnections.

```mermaid
graph TB

    subgraph REPO["📁 vat-fraud-detection (single git repo)"]

        subgraph IE_APP["Ireland VAT App — port 8501"]
            APP_ENTRY["app.py\nStreamlit entry point"]

            subgraph IE_PAGES["pages/"]
                P1["1_Invoice_Analyzer.py\nAnalysis queue runner"]
                P2["2_Prioritization_Dashboard.py\nRisk-ranked results"]
                P3["3_Case_View.py\nPer-invoice detail"]
                P4["4_History.py\nRe-queue past analyses"]
                P5["5_EU_Query.py\nBrowse Hub · Increment tab · Outbound log"]
                P6["6_Activity_Log.py\nLLM call log"]
            end

            subgraph IE_LIB["lib/"]
                ANALYSER["analyser.py\nRAG + LLM verdict engine"]
                EU_CLIENT["eu_client.py\nHTTP client → EU Hub API\nLogs all outbound calls"]
                IE_DB["database.py + db_seeder.py\nIrish invoice SQLite DB\n(vat_audit.db, cutoff 2026-03-25)"]
                PERSIST["persistence.py\nhistory.json + vat_audit.db sync"]
                RAG["rag.py + vector_store.py\nChromaDB retrieval"]
                MODELS_IE["models.py\nInvoice · LineItem\nAnalysisResult · VATVerdict"]
                ANA_LOG["analysis_log.py\nSQLite log of LLM calls"]
            end

            subgraph IE_DATA["data/"]
                VAT_DB[("vat_audit.db\nIrish invoices + analyses")]
                HIST[("history.json\nAnalysis session history")]
                ANA_DB[("analysis_log.db\nLLM activity log")]
                EU_LOG_DB[("eu_query_log.db\nOutbound request log")]
                CHROMA[("chroma_db/\nChromaDB vector store\nVAT legislation chunks")]
            end

            subgraph IE_PROMPTS["prompts/"]
                SYS_PROMPT["analysis_system.txt\nchat_system.txt\nextraction_system.txt"]
            end
        end

        subgraph EU_HUB_DIR["eu_vat_hub/"]

            subgraph EU_API["EU VAT Hub API — port 8503"]
                API_ENTRY["api.py\nFastAPI app\nLifespan: init_db + seed_if_empty"]

                subgraph EU_ENDPOINTS["REST endpoints"]
                    EP_HEALTH["GET /health"]
                    EP_LIST["GET /api/v1/invoices\n?country · date_from/to\n?tx_type · scope · treatment\n?description · limit · offset"]
                    EP_DETAIL["GET /api/v1/invoices/{id}"]
                    EP_STATS["GET /api/v1/stats/by-country\n/by-transaction-type\n/by-vat-treatment"]
                    EP_LOGS["GET /api/v1/logs"]
                end

                MIDDLEWARE["logging_middleware.py\nApiLoggingMiddleware\nCaptures: timestamp, method,\nendpoint, client_country,\nstatus, latency, records"]
            end

            subgraph EU_DASH["EU Hub Dashboard — port 8502"]
                HUB_APP["app.py\nStreamlit entry point"]
                subgraph HUB_PAGES["pages/"]
                    HP1["1_Overview.py\nKPIs + recent activity"]
                    HP2["2_Invoice_Browser.py\nFiltered invoice table"]
                    HP3["3_Analytics.py\nCharts by country / type / treatment"]
                    HP4["4_Activity_Log.py\nInbound request log (timestamped)"]
                end
            end

            subgraph EU_LIB["lib/"]
                EU_DB_LIB["database.py\ninit_db · query_invoices\ncount_invoices · get_invoice\nget_line_items · get_api_logs\nstats_by_* · write_api_log"]
                SEEDER["seeder.py\nSeed ~2,800 synthetic invoices\n(10 countries, realistic VAT errors)\n+ 25 IE increment records\n2026-03-26 to 2026-03-30"]
                EU_MODELS["models.py\nPydantic API models\n(no risk fields)"]
            end

            subgraph EU_DATA["data/"]
                EU_DB[("eu_vat.db\n~2,800 invoice records\n10 member states\nline_items · api_log tables")]
            end
        end
    end

    subgraph EXTERNAL["External (local)"]
        LM_STUDIO["LM Studio — port 1234\nChat model: VAT analysis\nEmbedding model: nomic-embed-text-v1.5"]
    end

    %% Ireland app internal wiring
    APP_ENTRY --> IE_PAGES
    P1 --> ANALYSER
    P5 --> EU_CLIENT
    P6 --> ANA_LOG
    ANALYSER --> RAG
    ANALYSER --> ANA_LOG
    RAG --> CHROMA
    PERSIST --> VAT_DB
    PERSIST --> HIST
    ANA_LOG --> ANA_DB
    EU_CLIENT --> EU_LOG_DB

    %% EU Hub internal wiring
    API_ENTRY --> EU_ENDPOINTS
    API_ENTRY --> MIDDLEWARE
    MIDDLEWARE --> EU_DB_LIB
    EU_ENDPOINTS --> EU_DB_LIB
    EU_DB_LIB --> EU_DB
    SEEDER --> EU_DB

    %% Cross-app
    EU_CLIENT -->|"HTTP · X-Client-Country: IE"| API_ENTRY
    ANALYSER -->|"OpenAI-compat API"| LM_STUDIO
    RAG -->|"Embeddings API"| LM_STUDIO

    %% Dashboard reads DB
    HUB_APP --> HUB_PAGES
    HUB_PAGES --> EU_DB_LIB
```

---

## 3. Data & Request Flows

### 3a. Increment fetch and analysis queue

```mermaid
sequenceDiagram
    actor Auditor
    participant App as Ireland App<br/>(port 8501)
    participant IrishDB as vat_audit.db<br/>(Irish DB)
    participant Client as eu_client.py
    participant OutLog as eu_query_log.db
    participant HubAPI as EU Hub API<br/>(port 8503)
    participant Middleware as ApiLoggingMiddleware
    participant HubDB as eu_vat.db

    Auditor->>App: Open EU Query → Increment tab
    Auditor->>App: Click "Fetch Increment from EU Hub"

    App->>Client: fetch_increment(limit=500)
    Client->>HubAPI: GET /api/v1/invoices<br/>?date_from=2026-03-26&limit=500<br/>X-Client-Country: IE

    HubAPI->>Middleware: intercept request
    Middleware->>HubDB: write_api_log(timestamp, IE, endpoint, …)

    HubAPI->>HubDB: query_invoices(date_from=2026-03-26)
    HubDB-->>HubAPI: 25 IE increment records
    HubAPI-->>Client: JSON {total, items[]}<br/>X-Records-Returned: 25

    Client->>OutLog: write_log(timestamp, GET, /api/v1/invoices, 200, latency, 25)
    Client-->>App: {items: [...]}

    App->>IrishDB: SELECT supplier_name, error_rate FROM invoices
    IrishDB-->>App: supplier stats

    App->>App: pre-classify each invoice<br/>error_rate ≥ 50% or gross > €15k → HIGH<br/>error_rate ≥ 15% → MEDIUM<br/>clean / new supplier → LOW / MEDIUM

    App-->>Auditor: Display classified invoices<br/>with checkboxes (sorted HIGH → MEDIUM → LOW)

    Auditor->>App: Tick invoices + click "Launch VAT Analysis"

    loop for each selected invoice_id
        App->>Client: get_invoice(invoice_id)
        Client->>HubAPI: GET /api/v1/invoices/{id}<br/>X-Client-Country: IE
        HubAPI->>Middleware: intercept
        Middleware->>HubDB: write_api_log(…)
        HubAPI-->>Client: InvoiceDetail (with line_items)
        Client->>OutLog: write_log(…)
        Client-->>App: InvoiceDetail dict
        App->>App: eu_detail_to_invoice(detail) → Invoice model
    end

    App->>App: st.session_state.analysis_queue = [Invoice, …]
    App-->>Auditor: Redirect → Invoice Analyzer page
```

### 3b. LLM compliance analysis

```mermaid
sequenceDiagram
    actor Auditor
    participant Analyzer as Invoice Analyzer<br/>(page 1)
    participant Analyser as lib/analyser.py
    participant RAG as lib/rag.py
    participant Chroma as ChromaDB<br/>chroma_db/
    participant LM as LM Studio<br/>(port 1234)
    participant Log as analysis_log.db
    participant Persist as lib/persistence.py
    participant DB as vat_audit.db

    Auditor->>Analyzer: Click "▶️ Run Analysis" (sidebar)

    loop for each Invoice in analysis_queue
        Analyzer->>Analyser: analyse(invoice)
        note over Analyser: record t₀

        loop for each line item
            Analyser->>RAG: retrieve(line_item)
            RAG->>LM: POST /v1/embeddings<br/>(description + category query)
            LM-->>RAG: embedding vector
            RAG->>Chroma: similarity search (top-k chunks)
            Chroma-->>RAG: legislation chunks [{document, source, url, …}]
        end

        Analyser->>Analyser: deduplicate + cap to 12 chunks<br/>format_context(chunks)

        Analyser->>LM: POST /v1/chat/completions<br/>system: analysis_system.txt<br/>user: invoice JSON + legislation context<br/>temperature: 0.0 · max_tokens: 4096
        LM-->>Analyser: JSON {verdicts: [{line_item_id, applied_rate,<br/>expected_rate, verdict, reasoning,<br/>legislation_refs}]}

        Analyser->>Analyser: parse verdicts<br/>_overall_verdict():<br/>any incorrect → incorrect<br/>all correct → correct<br/>else → uncertain

        Analyser->>Log: write_log(timestamp, invoice_number,<br/>supplier, model, line_count,<br/>verdict, latency_ms)
        Analyser-->>Analyzer: AnalysisResult

        Analyzer->>Persist: save_result(result)
        Persist->>DB: INSERT into analyses + invoices tables
        Persist->>Persist: append to history.json

        Analyzer-->>Auditor: Render result table (truncated rationale)<br/>+ "Full rationale" expander<br/>+ legislation excerpts<br/>+ voice button
    end

    Analyzer-->>Auditor: Batch summary<br/>(n correct · n incorrect · n uncertain)
```

### 3c. EU Hub inbound logging (all requests)

```mermaid
sequenceDiagram
    participant Any as Any member-state app<br/>(e.g. Ireland, France…)
    participant MW as ApiLoggingMiddleware
    participant Handler as FastAPI route handler
    participant DB as eu_vat.db<br/>(api_log table)
    participant Dash as EU Hub Dashboard<br/>(port 8502)
    actor EUAdmin as EU Administrator

    Any->>MW: HTTP request<br/>+ X-Client-Country header
    note over MW: record t₀

    MW->>Handler: forward request
    Handler->>DB: query invoices / stats / logs
    DB-->>Handler: results
    Handler-->>MW: response<br/>+ X-Records-Returned header

    note over MW: elapsed = now − t₀
    MW->>DB: INSERT api_log<br/>(timestamp UTC, method, endpoint,<br/>client_country, status_code,<br/>response_time_ms, records_returned)
    MW-->>Any: response (pass-through)

    EUAdmin->>Dash: Open Activity Log page
    Dash->>DB: get_api_logs(limit=N)
    DB-->>Dash: log rows
    Dash-->>EUAdmin: Table with formatted timestamps<br/>+ metrics + breakdown by country
```
