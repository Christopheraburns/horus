/**
 * NiFi ExecuteScript — adsb.lol flights -> canonical horus-events Kafka messages.
 *
 * Input:  FlowFile body = raw adsb.lol JSON from InvokeHTTP
 *         (GET https://api.adsb.lol/v2/point/{lat}/{lon}/{dist}; the aircraft
 *          array is under the top-level "ac" key). Run one InvokeHTTP per region
 *          and let this script process each response; OR merge regions upstream.
 * Output: One FlowFile per entity (envelope matching earthquakes-ingest.groovy).
 *
 * Script path inside container: /opt/nifi/conf/horus/scripts/flights-ingest.groovy
 *
 * Notes:
 *   - entityType = 'FLIGHT'; entity.properties.category ∈ {commercial, private, jet, military}
 *     is derived here (adsb.lol has no category field) by porting the Horus UI's
 *     classifyFlight() — type-code sets + dbFlags bit + callsign patterns.
 *   - Explicit f['key'] bracket access throughout (bean-accessor trap avoidance).
 *   - JsonOutput.toJson preserves numeric types (alt/speed/heading stay numbers).
 *   - No category_os (OpenSky) branch — source is adsb.lol. Add back if present.
 */
import org.apache.commons.io.IOUtils
import groovy.json.JsonSlurper
import groovy.json.JsonOutput
import java.time.Instant
import java.time.ZoneOffset
import java.time.format.DateTimeFormatter

def flowFile = session.get()
if (!flowFile) return

// ── classification tables (ported from the Horus UI classifyFlight) ──
def HELI_TYPES = [
    'R22','R44','R66','B06','B06T','B204','B205','B206','B212','B222','B230',
    'B407','B412','B427','B429','B430','B505','B525',
    'AS32','AS35','AS50','AS55','AS65',
    'EC20','EC25','EC30','EC35','EC45','EC55','EC75',
    'H125','H130','H135','H145','H155','H160','H175','H215','H225',
    'S55','S58','S61','S64','S70','S76','S92',
    'A109','A119','A139','A169','A189','AW09',
    'MD52','MD60','MDHI','MD90','NOTR',
    'B47G','HUEY','GAMA','CABR','EXE',
] as Set

def PRIVATE_JET_TYPES = [
    'G150','G200','G280','GLEX','G500','G550','G600','G650','G700',
    'GLF2','GLF3','GLF4','GLF5','GLF6','GL5T','GL7T','GV','GIV',
    'CL30','CL35','CL60','BD70','BD10',
    'C25A','C25B','C25C','C500','C510','C525','C550','C560','C56X','C680','C700','C750',
    'E35L','E50P','E55P','E545','E550',
    'FA50','FA7X','FA8X','F900','F2TH',
    'LJ35','LJ40','LJ45','LJ60','LJ70','LJ75',
    'PC12','PC24','TBM7','TBM8','TBM9',
    'PRM1','SF50','EA50','VLJ',
] as Set

def MILITARY_INDICATORS = [
    'C17','C5M','C130','C30J','KC10','KC46','KC35','E3CF','E3TF','E8A',
    'B1B','B2','B52','F16','F15','F18','F22','F35','A10','F117',
    'RC135','E6B','P8A','P3','MQ9','RQ4','U2','EP3','RC12',
    'V22','CH47','UH60','AH64','AH1Z','MV22',
    'EUFI','RFAL','TORD','TYP','GR4',
] as Set

// Known airliner models — used to keep genuine airliners out of the 'private' bucket
def AIRLINER_MODELS = [
    'A319','A320','A321','A332','A333','A339','A343','A359','A388',
    'B737','B738','B739','B38M','B39M','B752','B753','B763','B764',
    'B772','B77L','B77W','B788','B789','B78X',
    'E170','E175','E190','E195','CRJ7','CRJ9','AT43','AT72','DH8D',
] as Set

def AIRLINE_CODE_RE = ~/^([A-Z]{3})\d/
def MIL_CALLSIGN_RE = ~/(?i)^(RCH|KING|DUKE|EVAC|JAKE|REACH|CONVOY)\d/

def slurper = new JsonSlurper()
def raw = session.read(flowFile).text
def payload = slurper.parseText(raw)

// adsb.lol puts aircraft under "ac"
def aircraft = (payload?.get('ac')) ?: []
// Response time (epoch ms); each aircraft's seen_pos is its position's age in seconds.
def responseMs = (payload?.get('now') instanceof Number) ? (payload['now'] as long) : Instant.now().toEpochMilli()
def isoMs = { long ms -> Instant.ofEpochMilli(ms).atOffset(ZoneOffset.UTC).format(DateTimeFormatter.ofPattern("yyyy-MM-dd'T'HH:mm:ss'Z'")) }
def HEX_RE = ~/^[0-9a-f]{6}$/

def capturedAt = Instant.now().atOffset(ZoneOffset.UTC)
    .format(DateTimeFormatter.ofPattern("yyyy-MM-dd'T'HH:mm:ss'Z'"))
def ingestRunId = flowFile.getAttribute('ingest.run.id') ?: ('nifi-' + UUID.randomUUID().toString().take(12))

def provider  = 'adsb.lol'
def feed      = 'flights'
def sourceUrl = flowFile.getAttribute('invokehttp.request.url') ?: 'https://api.adsb.lol'
def emitted   = 0

aircraft.each { f ->
    // ── explicit bracket access (bean-accessor trap avoidance) ──
    def model     = ((f['t'] ?: '') as String).toUpperCase()
    def flightStr = ((f['flight'] ?: '') as String).trim().toUpperCase()
    def hex       = (f['hex'] ?: '') as String
    def dbFlags   = (f['dbFlags'] ?: 0) as Integer
    def lat       = f['lat']
    def lon       = f['lon']

    // Skip fixed structures and positionless records
    if (model == 'TWR') return
    if (lat == null || lon == null) return

    def callsign = flightStr ?: (hex ?: 'UNKNOWN')
    def altRaw   = f['alt_baro']
    def altMeters = (altRaw instanceof Number) ? ((altRaw as Double) * 0.3048) : 0.0d
    def speedKnots = (f['gs'] instanceof Number) ? (Math.round((f['gs'] as Double) * 10) / 10.0d) : null
    def heading  = (f['track'] instanceof Number) ? (f['track'] as Double) : 0.0d
    def isHeli   = HELI_TYPES.contains(model)
    def seenPos  = (f['seen_pos'] instanceof Number) ? (f['seen_pos'] as Double)
                 : ((f['seen'] instanceof Number) ? (f['seen'] as Double) : null)
    def reportedAt = seenPos != null ? isoMs(responseMs - (long) (seenPos * 1000d)) : capturedAt
    def motion = [
        speedMps  : (f['gs'] instanceof Number) ? (f['gs'] as Double) * 0.514444d : null,
        courseDeg : (f['track'] instanceof Number) ? (f['track'] as Double) : null,
        headingDeg: (f['true_heading'] instanceof Number) ? (f['true_heading'] as Double) : null,
    ]
    def idScheme = HEX_RE.matcher(hex).matches() ? 'icao24' : (hex ? 'adsb.lol' : 'callsign')
    def isGrounded = (altRaw instanceof Number) && ((altRaw as Double) < 100)

    // Extract airline code from callsign (e.g. UAL123 -> UAL)
    def airlineMatch = AIRLINE_CODE_RE.matcher(callsign)
    def airlineCode = airlineMatch.find() ? airlineMatch.group(1) : ''

    // ── classification (ported classifyFlight, no category_os) ──
    def category = 'commercial'
    if ((dbFlags & 1) || MILITARY_INDICATORS.contains(model) || MIL_CALLSIGN_RE.matcher(flightStr).find()) {
        category = 'military'
    } else if (PRIVATE_JET_TYPES.contains(model)) {
        category = 'jet'
    } else if (!airlineCode && model && !AIRLINER_MODELS.contains(model)) {
        category = 'private'
    }

    def entity = [
        id            : hex ?: callsign,
        name          : callsign,
        domain        : 'AIR',
        entityType    : 'FLIGHT',
        subtype       : category,
        position      : [
            lat: lat as Double,
            lng: lon as Double,
            alt: altMeters as Double,
        ],
        motion        : motion,
        threat        : (category == 'military') ? 'LOW' : 'NONE',
        classification: 'UNCLASSIFIED',
        releasability : null,
        confidence    : 0.9,
        timestamp     : reportedAt,
        source        : [
            provider  : provider,
            feed      : feed,
            originalId: hex ?: callsign,
            idScheme  : idScheme,
            confidence: 0.9,
            sourceUrl : sourceUrl,
        ],
        properties    : [
            callsign        : callsign,
            category        : category,           // commercial | private | jet | military
            aircraft_category: isHeli ? 'heli' : 'plane',
            model           : (f['t'] ?: 'Unknown'),
            icao24          : hex,
            registration    : (f['r'] ?: 'N/A'),
            squawk          : (f['squawk'] ?: ''),
            airline_code    : airlineCode,
            heading         : Math.round(heading),
            speed_knots     : speedKnots,
            grounded        : isGrounded,
            nac_p           : f['nac_p'],
        ],
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
    out = session.putAttribute(out, 'kafka.key', entity.id?.toString())
    out = session.putAttribute(out, 'trace.id', traceId)
    session.transfer(out, REL_SUCCESS)
    emitted++
}

if (emitted == 0) {
    log.warn('No flight entities emitted from adsb.lol payload')
    session.transfer(flowFile, REL_FAILURE)
} else {
    log.info("Emitted ${emitted} flight entities to Kafka path")
    session.remove(flowFile)
}
