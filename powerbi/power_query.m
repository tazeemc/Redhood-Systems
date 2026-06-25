// ============================================================================
// RedHood Systems — Power Query M Scripts
// ============================================================================
// These are the M (Power Query) transformations for each table.
// In Power BI Desktop: Home > Transform Data > Advanced Editor > paste per query.
//
// OPTION A — Import from CSV (after running export_to_powerbi.py)
// OPTION B — Connect directly to SQLite (requires SQLite ODBC driver)
//
// The CSV import option is recommended for most users.
// ============================================================================


// ── OPTION A: CSV IMPORTS ─────────────────────────────────────────────────────

// --- dim_runs ----------------------------------------------------------------
let
    Source = Csv.Document(
        File.Contents("C:\Users\ctaze\Downloads\Redhood-Systems\powerbi\data\dim_runs.csv"),
        [Delimiter=",", Columns=10, Encoding=65001, QuoteStyle=QuoteStyle.None]
    ),
    PromotedHeaders = Table.PromoteHeaders(Source, [PromoteAllScalars=true]),
    ChangedTypes = Table.TransformColumnTypes(PromotedHeaders, {
        {"run_id",               Int64.Type},
        {"run_at",               type text},
        {"run_date",             type date},
        {"run_hour",             Int64.Type},
        {"run_day_of_week",      type text},
        {"hours_back",           type number},
        {"feeds_collected",      Int64.Type},
        {"narratives_extracted", Int64.Type},
        {"json_path",            type text},
        {"html_path",            type text}
    })
in
    ChangedTypes


// --- dim_accounts ------------------------------------------------------------
let
    Source = Csv.Document(
        File.Contents("C:\Users\ctaze\Downloads\Redhood-Systems\powerbi\data\dim_accounts.csv"),
        [Delimiter=",", Columns=8, Encoding=65001, QuoteStyle=QuoteStyle.None]
    ),
    PromotedHeaders = Table.PromoteHeaders(Source, [PromoteAllScalars=true]),
    ChangedTypes = Table.TransformColumnTypes(PromotedHeaders, {
        {"account_id",  Int64.Type},
        {"handle",      type text},
        {"handle_at",   type text},
        {"added_at",    type text},
        {"added_date",  type date},
        {"active",      type text},
        {"category",    type text},
        {"notes",       type text}
    })
in
    ChangedTypes


// --- fact_feeds --------------------------------------------------------------
let
    Source = Csv.Document(
        File.Contents("C:\Users\ctaze\Downloads\Redhood-Systems\powerbi\data\fact_feeds.csv"),
        [Delimiter=",", Columns=12, Encoding=65001, QuoteStyle=QuoteStyle.None]
    ),
    PromotedHeaders = Table.PromoteHeaders(Source, [PromoteAllScalars=true]),
    ChangedTypes = Table.TransformColumnTypes(PromotedHeaders, {
        {"feed_id",          type text},
        {"run_id",           Int64.Type},
        {"source",           type text},
        {"author",           type text},
        {"content_clean",    type text},
        {"word_count",       Int64.Type},
        {"published_at",     type text},
        {"published_date",   type date},
        {"published_hour",   Int64.Type},
        {"published_dow",    type text},
        {"url",              type text},
        {"nitter_instance",  type text}
    })
in
    ChangedTypes


// --- fact_narratives ---------------------------------------------------------
let
    Source = Csv.Document(
        File.Contents("C:\Users\ctaze\Downloads\Redhood-Systems\powerbi\data\fact_narratives.csv"),
        [Delimiter=",", Columns=19, Encoding=65001, QuoteStyle=QuoteStyle.None]
    ),
    PromotedHeaders = Table.PromoteHeaders(Source, [PromoteAllScalars=true]),
    ChangedTypes = Table.TransformColumnTypes(PromotedHeaders, {
        {"narrative_id",          type text},
        {"run_id",                Int64.Type},
        {"run_at",                type text},
        {"title",                 type text},
        {"entropy_risk",          Int64.Type},
        {"entropy_band",          type text},
        {"hypothesis",            type text},
        {"rationale",             type text},
        {"catalysts",             type text},
        {"catalyst_count",        Int64.Type},
        {"bear_case",             type text},
        {"disconfirming_signals", type text},
        {"conviction_adjustment", type text},
        {"conviction_size",       Int64.Type},
        {"created_at",            type text},
        {"created_date",          type date},
        {"created_hour",          Int64.Type},
        {"created_dow",           type text},
        {"supporting_feed_count", Int64.Type}
    }),
    // Add entropy band sort order for correct chart sequencing
    AddedBandOrder = Table.AddColumn(ChangedTypes, "entropy_band_order",
        each if [entropy_band] = "Low (1-3)"      then 1
        else if [entropy_band] = "Medium (4-6)"   then 2
        else if [entropy_band] = "High (7-8)"     then 3
        else if [entropy_band] = "Critical (9-10)"then 4
        else 0,
        Int64.Type
    )
in
    AddedBandOrder


// --- bridge_narrative_feeds --------------------------------------------------
let
    Source = Csv.Document(
        File.Contents("C:\Users\ctaze\Downloads\Redhood-Systems\powerbi\data\bridge_narrative_feeds.csv"),
        [Delimiter=",", Columns=2, Encoding=65001, QuoteStyle=QuoteStyle.None]
    ),
    PromotedHeaders = Table.PromoteHeaders(Source, [PromoteAllScalars=true]),
    ChangedTypes = Table.TransformColumnTypes(PromotedHeaders, {
        {"narrative_id", type text},
        {"feed_id",      type text}
    })
in
    ChangedTypes


// ── OPTION B: DIRECT SQLITE CONNECTION ───────────────────────────────────────
// Requires the SQLite ODBC driver: https://www.ch-werner.de/sqliteodbc/
//
// To use: replace the DSN string with your actual path.
//
// let
//     Source = Odbc.DataSource(
//         "Driver={SQLite3 ODBC Driver};Database=C:\Users\ctaze\Downloads\Redhood-Systems\redhood.db",
//         [HierarchicalNavigation=true]
//     ),
//     RedHoodDB = Source{[Name="redhood"]}[Data],
//     NarrativesTable = RedHoodDB{[Name="narratives"]}[Data]
// in
//     NarrativesTable


// ── SHARED HELPER: DATE TABLE ─────────────────────────────────────────────────
// Create a separate Date dimension table for time intelligence DAX functions.
// New Table > paste this formula:
//
// DateTable =
// CALENDAR(
//     DATE(2026, 1, 1),
//     DATE(2026, 12, 31)
// )
//
// Then add calculated columns:
//   Year        = YEAR(DateTable[Date])
//   Month       = FORMAT(DateTable[Date], "MMMM")
//   MonthNum    = MONTH(DateTable[Date])
//   Week        = WEEKNUM(DateTable[Date])
//   DayOfWeek   = FORMAT(DateTable[Date], "dddd")
//   Quarter     = "Q" & FORMAT(DateTable[Date], "Q")
//
// Then mark it as a Date Table (right-click > Mark as date table > Date column).


// ── ADDED 2026-05 AUDIT ──────────────────────────────────────────────────────
// New tables produced by export_to_powerbi.py after `score_narratives.py`
// + `redhood_pnl.py` have been run.

// --- fact_narrative_tickers --------------------------------------------------
let
    Source = Csv.Document(
        File.Contents("C:\Users\ctaze\Downloads\Redhood-Systems\powerbi\data\fact_narrative_tickers.csv"),
        [Delimiter=",", Columns=8, Encoding=65001, QuoteStyle=QuoteStyle.None]
    ),
    PromotedHeaders = Table.PromoteHeaders(Source, [PromoteAllScalars=true]),
    ChangedTypes = Table.TransformColumnTypes(PromotedHeaders, {
        {"narrative_id",   type text},
        {"ticker",         type text},
        {"side",           type text},
        {"is_long_equity", Int64.Type},
        {"extracted_at",   type text},
        {"entry_date",     type date},
        {"entry_close",    type number},
        {"last_close",     type number}
    })
in
    ChangedTypes


// --- fact_narrative_grades ---------------------------------------------------
let
    Source = Csv.Document(
        File.Contents("C:\Users\ctaze\Downloads\Redhood-Systems\powerbi\data\fact_narrative_grades.csv"),
        [Delimiter=",", Columns=8, Encoding=65001, QuoteStyle=QuoteStyle.None]
    ),
    PromotedHeaders = Table.PromoteHeaders(Source, [PromoteAllScalars=true]),
    ChangedTypes = Table.TransformColumnTypes(PromotedHeaders, {
        {"narrative_id",   type text},
        {"specificity",    Int64.Type},
        {"catalyst_score", Int64.Type},
        {"risk_score",     Int64.Type},
        {"cohesion",       Int64.Type},
        {"total_score",    Int64.Type},
        {"letter_grade",   type text},
        {"graded_at",      type text}
    })
in
    ChangedTypes


// --- fact_prices -------------------------------------------------------------
let
    Source = Csv.Document(
        File.Contents("C:\Users\ctaze\Downloads\Redhood-Systems\powerbi\data\fact_prices.csv"),
        [Delimiter=",", Columns=5, Encoding=65001, QuoteStyle=QuoteStyle.None]
    ),
    PromotedHeaders = Table.PromoteHeaders(Source, [PromoteAllScalars=true]),
    ChangedTypes = Table.TransformColumnTypes(PromotedHeaders, {
        {"ticker",      type text},
        {"price_date",  type date},
        {"close",       type number},
        {"fetched_at",  type text},
        {"source",      type text}
    })
in
    ChangedTypes
