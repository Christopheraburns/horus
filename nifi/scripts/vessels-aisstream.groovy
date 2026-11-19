/**
 * NiFi ExecuteScript — aisstream.io AIS -> canonical horus-events Kafka messages.
 *
 * Input:  FlowFile body = one aisstream.io JSON message, as emitted by
 *         ConnectWebSocket (wss://stream.aisstream.io/v0/stream). Two message
 *         types are handled:
 *           - PositionReport : position + course/speed (MMSI-keyed, no IMO)
 *           - ShipStaticData : name, destination, dimensions, IMO (when non-zero)
 * Output: One FlowFile per vessel (envelope matching earthquakes-ingest.groovy).
 *
 * Script path inside container: /opt/nifi/conf/horus/scripts/vessels-ingest.groovy
 *
 * Design (per demo decision):
 *   - Vessels are keyed on MMSI (always present) — this is entity.id / kafka.key.
 *     Position reports keep vessels moving on the canvas; no correlation state.
 *   - IMO is carried as a property ONLY when a ShipStaticData message has a
 *     non-zero ImoNumber. Many AIS vessels transmit IMO 0 (non-SOLAS craft) —
 *     those simply have no imo property and won't enrich. That's expected.
 *   - Enrichment (vessel -> graph by IMO) is best-effort: it fires for the subset
 *     of vessels that both broadcast a real IMO AND exist in the graph.
 *
 * Explicit f['key'] bracket access throughout (Groovy bean-accessor trap).
 * JsonOutput.toJson preserves numeric types.
 */
import groovy.json.JsonSlurper
import groovy.json.JsonOutput
import java.time.Instant
import java.time.ZoneOffset
import java.time.format.DateTimeFormatter

def flowFile = session.get()
if (!flowFile) return

def slurper = new JsonSlurper()
def raw = session.read(flowFile).text
def msg
try {
    msg = slurper.parseText(raw)
} catch (Exception e) {
    log.warn("Unparseable AIS message: ${e.message}")
    session.transfer(flowFile, REL_FAILURE)
    return
}

def msgType  = msg['MessageType']
def meta     = msg['MetaData'] ?: [:]
def message  = msg['Message'] ?: [:]

// MMSI is the stable key, present in MetaData on every message type.
def mmsi = meta['MMSI']
if (mmsi == null) {
    // Nothing we can key on — drop quietly (not a failure, just unusable).
    session.remove(flowFile)
    return
}
def mmsiStr = mmsi.toString()

// Position lives in MetaData on both message types (convenient).
def lat = meta['latitude']
def lng = meta['longitude']
if (lat == null || lng == null) {
    session.remove(flowFile)
    return
}

// Ship name: trim the fixed-width AIS padding.
def shipName = ((meta['ShipName'] ?: '') as String).trim()

// ── type-specific fields ──
def props = [
    mmsi     : mmsi,
    msgType  : msgType,
]

if (msgType == 'PositionReport') {
    def pr = message['PositionReport'] ?: [:]
    props['cog']      = pr['Cog']                 // course over ground (deg)
    props['sog']      = pr['Sog']                 // speed over ground (knots)
    props['heading']  = pr['TrueHeading']         // true heading (deg)
    props['navStatus']= pr['NavigationalStatus']
} else if (msgType == 'ShipStaticData') {
    def sd = message['ShipStaticData'] ?: [:]
    if (!shipName) shipName = ((sd['Name'] ?: '') as String).trim()
    props['callsign']    = ((sd['CallSign'] ?: '') as String).trim()
    props['destination'] = ((sd['Destination'] ?: '') as String).trim()
    props['shipType']    = sd['Type']             // AIS ship type code
    props['draught']     = sd['MaximumStaticDraught']
    // IMO — only carry it when it's a real (non-zero) number. This is the
    // graph join key; absent/zero means the vessel won't enrich.
    def imo = sd['ImoNumber']
    if (imo != null && (imo as Long) > 0) {
        props['imo'] = imo
    }
    // Dimensions -> overall length/width (A+B, C+D) if present.
    def dim = sd['Dimension']
    if (dim instanceof Map) {
        def a = dim['A']; def b = dim['B']; def c = dim['C']; def d = dim['D']
        if (a != null && b != null) props['length'] = (a as Integer) + (b as Integer)
        if (c != null && d != null) props['width']  = (c as Integer) + (d as Integer)
    }
} else {
    // Unhandled message type — drop quietly.
    session.remove(flowFile)
    return
}

def capturedAt = Instant.now().atOffset(ZoneOffset.UTC)
    .format(DateTimeFormatter.ofPattern("yyyy-MM-dd'T'HH:mm:ss'Z'"))
// The report's own time: MetaData.time_utc is "2026-11-19 18:01:58.123456789 +0000 UTC".
def timeUtc = (meta['time_utc'] ?: '') as String
def reportedAt = (timeUtc ==~ /^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}.*/)
    ? timeUtc.substring(0, 10) + 'T' + timeUtc.substring(11, 19) + 'Z' : capturedAt

// Envelope v2 motion, in SI units, only what this message reports.
def num = { v -> (v instanceof Number) ? (v as Double) : null }
def motion = null
if (msgType == 'PositionReport') {
    def sog = num(props['sog']); def cog = num(props['cog']); def hdg = num(props['heading'])
    motion = [
        speedMps  : (sog != null && sog < 102.3) ? sog * 0.514444d : null,   // 102.3 = not available
        courseDeg : (cog != null && cog < 360) ? cog : null,                 // 360 = not available
        headingDeg: (hdg != null && hdg < 360) ? hdg : null,                 // 511 = not available
    ]
}
// AIS ship type code -> Horus vessel type (same mapping as the gateway).
def shipType = num(props['shipType'])
def subtype = null
if (shipType) {
    def code = shipType as int
    subtype = (code >= 80 && code <= 89) ? 'tanker' : (code == 35 ? 'military' : 'cargo')
}
def ingestRunId = flowFile.getAttribute('ingest.run.id') ?: ('nifi-' + UUID.randomUUID().toString().take(12))

def provider = 'aisstream.io'
def feed     = 'vessels'
def sourceUrl = flowFile.getAttribute('invokehttp.request.url') ?: 'wss://stream.aisstream.io/v0/stream'

def entity = [
    id            : mmsiStr,
    name          : shipName ?: mmsiStr,
    domain        : 'SEA',
    entityType    : 'VESSEL',
    subtype       : subtype,
    position      : [
        lat: lat as Double,
        lng: lng as Double,
        alt: null,
    ],
    motion        : motion,
    threat        : 'NONE',
    classification: 'UNCLASSIFIED',
    releasability : null,
    confidence    : 0.9,
    timestamp     : reportedAt,
    source        : [
        provider  : provider,
        feed      : feed,
        originalId: mmsiStr,
        idScheme  : 'mmsi',
        confidence: 0.9,
        sourceUrl : sourceUrl,
    ],
    properties    : props,
]

def traceId = UUID.randomUUID().toString()

def envelope = [
    schema_version: 2,
    trace_id      : traceId,
    ingest_run_id : ingestRunId,
    source        : feed,
    captured_at   : capturedAt,
    entity        : entity,
]

def out = session.create(flowFile)
out = session.write(out, { outStream ->
    outStream.write(JsonOutput.toJson(envelope).getBytes('UTF-8'))
} as OutputStreamCallback)
out = session.putAttribute(out, 'mime.type', 'application/json')
out = session.putAttribute(out, 'kafka.key', mmsiStr)
out = session.putAttribute(out, 'trace.id', traceId)
session.transfer(out, REL_SUCCESS)
session.remove(flowFile)
