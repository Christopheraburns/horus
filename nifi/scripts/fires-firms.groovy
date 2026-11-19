/**
 * NiFi ExecuteScript — NASA FIRMS active-fire CSV -> canonical horus-events Kafka messages.
 *
 * Input:  FlowFile body = FIRMS Global 24h CSV (VIIRS or MODIS) from InvokeHTTP
 * Output: One FlowFile per fire entity (canonical envelope, entityType FIRE)
 *
 * Mirrors src/app/api/fires/route.ts parseCSV(): handles both VIIRS (bright_ti4)
 * and MODIS (brightness) headers, samples down to ~MAX_POINTS rows to match the
 * direct-API behavior, rounds coords to 3 decimals.
 *
 * NOTE (CFM/Groovy): read a JSON key named "properties" with .get('properties');
 * both .properties and ['properties'] can resolve to the bean accessor in NiFi.
 */
import org.apache.commons.io.IOUtils
import groovy.json.JsonOutput
import java.time.Instant
import java.time.ZoneOffset
import java.time.format.DateTimeFormatter

final int MAX_POINTS = 2000

def flowFile = session.get()
if (!flowFile) return

def raw = session.read(flowFile).text
def lines = raw.trim().split('\n')
if (lines.length < 2) {
    log.warn('FIRMS CSV empty or header-only')
    session.transfer(flowFile, REL_FAILURE)
    return
}

def header = lines[0].split(',')*.trim()
def latIdx    = header.indexOf('latitude')
def lngIdx    = header.indexOf('longitude')
def brightIdx = header.indexOf('bright_ti4') != -1 ? header.indexOf('bright_ti4') : header.indexOf('brightness')
def confIdx   = header.indexOf('confidence')
def dateIdx   = header.indexOf('acq_date')
def timeIdx   = header.indexOf('acq_time')
def frpIdx    = header.indexOf('frp')
def satIdx    = header.indexOf('satellite')

if (latIdx == -1 || lngIdx == -1) {
    log.warn("FIRMS CSV missing lat/lng columns: ${header}")
    session.transfer(flowFile, REL_FAILURE)
    return
}

def capturedAt = Instant.now().atOffset(ZoneOffset.UTC)
    .format(DateTimeFormatter.ofPattern("yyyy-MM-dd'T'HH:mm:ss'Z'"))
def ingestRunId = flowFile.getAttribute('ingest.run.id') ?: ('nifi-' + UUID.randomUUID().toString().take(12))
def sourceUrl = flowFile.getAttribute('invokehttp.request.url') ?: 'https://firms.modaps.eosdis.nasa.gov'
def feedName  = sourceUrl.contains('SUOMI') || sourceUrl.contains('viirs')
    ? 'NASA-FIRMS (VIIRS)' : 'NASA-FIRMS (MODIS)'

// Sample: every Nth row so we emit at most ~MAX_POINTS (matches route.ts).
int dataRows = lines.length - 1
int step = dataRows > MAX_POINTS ? (int) Math.ceil(dataRows / (double) MAX_POINTS) : 1
def emitted = 0

for (int i = 1; i < lines.length; i += step) {
    def cols = lines[i].split(',')
    if (cols.length <= Math.max(latIdx, lngIdx)) continue
    def lat = cols[latIdx]?.isDouble() ? (cols[latIdx] as Double) : null
    def lng = cols[lngIdx]?.isDouble() ? (cols[lngIdx] as Double) : null
    if (lat == null || lng == null) continue
    lat = Math.round(lat * 1000d) / 1000d
    lng = Math.round(lng * 1000d) / 1000d

    def brightness = (brightIdx != -1 && cols.length > brightIdx && cols[brightIdx]?.isDouble()) ? (cols[brightIdx] as Double) : null
    def frp        = (frpIdx    != -1 && cols.length > frpIdx    && cols[frpIdx]?.isDouble())    ? (cols[frpIdx] as Double)    : null
    def confidence = (confIdx   != -1 && cols.length > confIdx) ? cols[confIdx]?.trim() : null
    def acqDate    = (dateIdx   != -1 && cols.length > dateIdx) ? cols[dateIdx]?.trim() : ''
    def acqTime    = (timeIdx   != -1 && cols.length > timeIdx) ? cols[timeIdx]?.trim() : ''
    def satellite  = (satIdx    != -1 && cols.length > satIdx)  ? cols[satIdx]?.trim()  : null

    // Stable-ish id: satellite + position + acquisition; FIRMS has no row id.
    def fireId = "firms-${satellite ?: 'x'}-${lat}-${lng}-${acqDate}-${acqTime}"
    def traceId = UUID.randomUUID().toString()

    // Event time from acq_date + acq_time (HHMM); fall back to capture time.
    def eventTime = capturedAt
    if (acqDate) {
        def hhmm = acqTime?.isInteger() ? String.format('%04d', acqTime as Integer) : '0000'
        eventTime = "${acqDate}T${hhmm[0..1]}:${hhmm[2..3]}:00Z"
    }

    def entity = [
        id            : fireId,
        name          : "Fire detection (${feedName})",
        domain        : 'LAND',
        entityType    : 'FIRE',
        subtype       : 'satellite-detection',
        position      : [lat: lat, lng: lng, alt: null],
        threat        : 'NONE',
        classification: 'UNCLASSIFIED',
        releasability : null,
        confidence    : 0.8,
        timestamp     : eventTime,
        source        : [
            provider  : 'NASA-FIRMS',
            feed      : 'fires',
            originalId: fireId,
            idScheme  : 'firms',
            confidence: 0.8,
            sourceUrl : sourceUrl,
            updated   : null,
        ],
        properties    : [
            brightness: brightness,
            confidence: confidence,
            frp       : frp,
            date      : acqDate,
            time      : acqTime,
            satellite : satellite,
            firetype  : 'satellite-detection',
            sourceName: feedName,
        ],
    ]

    def envelope = [
        schema_version: 2,
        trace_id      : traceId,
        ingest_run_id : ingestRunId,
        source        : 'fires',
        captured_at   : capturedAt,
        entity        : entity,
    ]

    def out = session.create(flowFile)
    out = session.write(out, { outStream ->
        outStream.write(JsonOutput.toJson(envelope).getBytes('UTF-8'))
    } as OutputStreamCallback)
    out = session.putAttribute(out, 'mime.type', 'application/json')
    out = session.putAttribute(out, 'kafka.key', fireId)
    out = session.putAttribute(out, 'trace.id', traceId)
    session.transfer(out, REL_SUCCESS)
    emitted++
}

if (emitted == 0) {
    log.warn('No fire entities emitted from FIRMS payload')
    session.transfer(flowFile, REL_FAILURE)
} else {
    log.info("Emitted ${emitted} fire entities (of ${dataRows} rows, step ${step}) to Kafka path")
    session.remove(flowFile)
}