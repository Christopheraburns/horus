/**
 * NiFi ExecuteScript — NOAA/NWS active alerts -> canonical horus-events Kafka messages.
 *
 * Input:  FlowFile body = NWS GeoJSON from InvokeHTTP
 *         (https://api.weather.gov/alerts/active?status=actual&message_type=alert
 *          — set InvokeHTTP request headers: Accept: application/geo+json,
 *          User-Agent: "HORUS SEVERE WEATHER LAYER (#{http.contact})"; NWS rejects UA-less requests)
 * Output: One FlowFile per WEATHER entity.
 *
 * Mirrors the NWS branch of src/app/api/weather/route.ts: representative point
 * from Point/Polygon/MultiPolygon geometry, Extreme|Severe->high /
 * Moderate->medium / else low severity.
 *
 * NOTE (CFM/Groovy): NWS GeoJSON features have a "properties" key — ALWAYS use
 * f.get('properties'): both f.properties and f['properties'] can resolve to the
 * map's bean properties in NiFi's Groovy (seen on CFM, 2026-11-19).
 */
import org.apache.commons.io.IOUtils
import groovy.json.JsonSlurper
import groovy.json.JsonOutput
import java.time.Instant
import java.time.ZoneOffset
import java.time.format.DateTimeFormatter

def flowFile = session.get()
if (!flowFile) return

def slurper = new JsonSlurper()
def raw = session.read(flowFile).text
def data = slurper.parseText(raw)

def capturedAt = Instant.now().atOffset(ZoneOffset.UTC)
    .format(DateTimeFormatter.ofPattern("yyyy-MM-dd'T'HH:mm:ss'Z'"))
def ingestRunId = flowFile.getAttribute('ingest.run.id') ?: ('nifi-' + UUID.randomUUID().toString().take(12))
def sourceUrl = flowFile.getAttribute('invokehttp.request.url') ?: 'https://api.weather.gov/alerts/active'
def emitted = 0

// Average of a ring of [lng, lat] pairs -> [lat, lng], mirroring averageCoordinates().
def avgCoords = { List ring ->
    if (!ring) return null
    double lat = 0d, lng = 0d
    ring.each { c -> lng += (c[0] as Double); lat += (c[1] as Double) }
    [lat / ring.size(), lng / ring.size()]
}

// Point / Polygon(first ring) / MultiPolygon(first poly, first ring) -> [lat, lng].
def repPoint = { Map geom ->
    if (!geom) return null
    def coords = geom['coordinates']
    if (geom['type'] == 'Point' && coords)        return [coords[1] as Double, coords[0] as Double]
    if (geom['type'] == 'Polygon')                return avgCoords(coords ? coords[0] : null)
    if (geom['type'] == 'MultiPolygon')           return avgCoords((coords && coords[0]) ? coords[0][0] : null)
    return null
}

// Envelope v2 shape: the alert's polygon as WKT, with its bounding box. Points have none.
def ringWkt = { List ring -> '(' + ring.collect { c -> "${c[0] as Double} ${c[1] as Double}" }.join(', ') + ')' }
def polyWkt = { List rings -> '(' + rings.collect { r -> ringWkt(r as List) }.join(', ') + ')' }
def shapeOf = { Map geom ->
    if (!geom || !geom['coordinates']) return null
    def coords = geom['coordinates']
    def wkt = null; def points = []
    if (geom['type'] == 'Polygon') {
        wkt = 'POLYGON ' + polyWkt(coords as List)
        coords.each { r -> points.addAll(r) }
    } else if (geom['type'] == 'MultiPolygon') {
        wkt = 'MULTIPOLYGON (' + coords.collect { p -> polyWkt(p as List) }.join(', ') + ')'
        coords.each { p -> p.each { r -> points.addAll(r) } }
    }
    if (!wkt || !points) return null
    def lons = points.collect { c -> c[0] as Double }; def lats = points.collect { c -> c[1] as Double }
    [wkt: wkt, bbox: [lons.min(), lats.min(), lons.max(), lats.max()]]
}

def normalizeSeverity = { String s ->
    if (s == 'Extreme' || s == 'Severe') return 'high'
    if (s == 'Moderate') return 'medium'
    return 'low'
}

(data['features'] ?: []).each { f ->
    // Map.get, not f['properties']: on the platform's NiFi the subscript returned the
    // map's bean properties, so every alert lost its headline, times and area.
    def props = (f instanceof Map ? f.get('properties') : null) ?: [:]
    def pt = repPoint(f['geometry'] as Map)
    if (pt == null) return
    def (lat, lng) = pt
    def shape = shapeOf(f['geometry'] as Map)

    def alertId   = props['id'] ?: props['@id'] ?: props['event'] ?: lat.toString()
    def entityId  = "nws-${alertId}".toString()
    def title     = props['headline'] ?: props['event'] ?: 'NWS Weather Alert'
    def eventDate = props['effective'] ?: props['sent'] ?: capturedAt
    // NWS times carry a local offset (-06:00); the envelope's timestamp is UTC.
    def eventUtc = capturedAt
    try {
        eventUtc = java.time.OffsetDateTime.parse(eventDate.toString()).withOffsetSameInstant(ZoneOffset.UTC)
            .format(DateTimeFormatter.ofPattern("yyyy-MM-dd'T'HH:mm:ss'Z'"))
    } catch (Exception ignored) { }
    def traceId   = UUID.randomUUID().toString()

    def entity = [
        id            : entityId,
        name          : title.toString(),
        domain        : 'AIR',
        entityType    : 'WEATHER',
        subtype       : 'weatherAlerts',
        position      : [lat: lat, lng: lng, alt: null],
        geometry      : shape?.wkt,
        bbox          : shape?.bbox,
        threat        : 'NONE',
        classification: 'UNCLASSIFIED',
        releasability : null,
        confidence    : 0.9,
        timestamp     : eventUtc,
        source        : [
            provider  : 'NOAA/NWS',
            feed      : 'weather',
            originalId: alertId.toString(),
            idScheme  : 'nws',
            confidence: 0.9,
            sourceUrl : sourceUrl,
            updated   : null,
        ],
        properties    : [
            title    : title,
            category : 'weatherAlerts',
            wxtype   : props['event'] ?: 'Weather Alert',
            icon     : 'weather',
            severity : normalizeSeverity(props['severity'] as String),
            date     : eventDate,
            expires  : props['expires'],
            area     : props['areaDesc'],
            eventSrc : props['@id'] ?: 'https://api.weather.gov/alerts/active',
            provider : 'NOAA/NWS',
        ],
    ]

    def envelope = [
        schema_version: 2,
        trace_id      : traceId,
        ingest_run_id : ingestRunId,
        source        : 'weather',
        captured_at   : capturedAt,
        entity        : entity,
    ]

    def out = session.create(flowFile)
    out = session.write(out, { outStream ->
        outStream.write(JsonOutput.toJson(envelope).getBytes('UTF-8'))
    } as OutputStreamCallback)
    out = session.putAttribute(out, 'mime.type', 'application/json')
    out = session.putAttribute(out, 'kafka.key', entityId)
    out = session.putAttribute(out, 'trace.id', traceId)
    session.transfer(out, REL_SUCCESS)
    emitted++
}

if (emitted == 0) {
    log.warn('No NWS alert entities emitted')
    session.transfer(flowFile, REL_FAILURE)
} else {
    log.info("Emitted ${emitted} NWS weather entities to Kafka path")
    session.remove(flowFile)
}