/**
 * NiFi ExecuteScript — NASA EONET open events -> canonical horus-events Kafka messages.
 *
 * Input:  FlowFile body = EONET v3 JSON (https://eonet.gsfc.nasa.gov/api/v3/events?status=open&limit=100)
 * Output: One FlowFile per WEATHER entity. Volcanoes are ALSO emitted a second
 *         time as FIRE entities (distinct id prefix) so the fires map layer keeps
 *         its volcano markers — parity with the direct-API behavior where
 *         volcanoes appear on both layers.
 *
 * Mirrors src/app/api/weather/route.ts (EONET branch) and the volcano block of
 * src/app/api/fires/route.ts.
 *
 * NOTE (CFM/Groovy): use f['key'] access, except for a key named "properties": read
 * that with .get('properties'). Both .properties and ['properties'] can resolve to the
 * bean accessor in NiFi (it nulled earthquake magnitudes, then NWS alert fields).
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
def sourceUrl = flowFile.getAttribute('invokehttp.request.url') ?: 'https://eonet.gsfc.nasa.gov'
def emitted = 0

// Emit one canonical envelope FlowFile. Returns nothing; increments emitted.
def emit = { Map entity ->
    def traceId = UUID.randomUUID().toString()
    def envelope = [
        schema_version: 2,
        trace_id      : traceId,
        ingest_run_id : ingestRunId,
        source        : entity['source']['feed'],
        captured_at   : capturedAt,
        entity        : entity,
    ]
    def out = session.create(flowFile)
    out = session.write(out, { outStream ->
        outStream.write(JsonOutput.toJson(envelope).getBytes('UTF-8'))
    } as OutputStreamCallback)
    out = session.putAttribute(out, 'mime.type', 'application/json')
    out = session.putAttribute(out, 'kafka.key', entity['id'].toString())
    out = session.putAttribute(out, 'trace.id', traceId)
    session.transfer(out, REL_SUCCESS)
    emitted++
}

(data['events'] ?: []).each { e ->
    def geoms = e['geometry'] ?: []
    if (!geoms) return
    def geom = geoms[geoms.size() - 1]                    // latest geometry, like route.ts
    if (geom['type'] != 'Point' || !geom['coordinates']) return
    def coords = geom['coordinates']
    def lat = coords.size() > 1 ? coords[1] as Double : null
    def lng = coords.size() > 0 ? coords[0] as Double : null
    if (lat == null || lng == null) return

    def cats = e['categories'] ?: []
    def category = (cats ? cats[0]['id'] : null) ?: 'unknown'

    // Parity with route.ts: skip wildfires (FIRMS owns them) and earthquakes (own feed).
    if (category == 'wildfires' || category == 'earthquakes') return

    def typeLabel = 'Event'; def icon = 'alert'; def severity = 'low'
    if (category == 'severeStorms')      { typeLabel = 'Severe Storm';      icon = 'cyclone'; severity = 'high' }
    else if (category == 'volcanoes')    { typeLabel = 'Volcano Eruption';  icon = 'volcano'; severity = 'high' }
    else if (category == 'seaIce')       { typeLabel = 'Iceberg / Sea Ice'; icon = 'ice';     severity = 'medium' }
    else                                 { typeLabel = (cats ? cats[0]['title'] : null) ?: 'Anomaly' }

    def eventDate = geom['date'] ?: capturedAt
    def srcs = e['sources'] ?: []
    def eventSource = (srcs ? srcs[0]['url'] : null) ?: 'NASA EONET'

    // ── WEATHER entity (all retained categories) ──
    emit([
        id            : "eonet-${e['id']}".toString(),
        name          : e['title']?.toString(),
        domain        : 'AIR',
        entityType    : 'WEATHER',
        subtype       : category,
        position      : [lat: lat, lng: lng, alt: null],
        threat        : 'NONE',
        classification: 'UNCLASSIFIED',
        releasability : null,
        confidence    : 0.9,
        timestamp     : eventDate,
        source        : [
            provider  : 'NASA EONET',
            feed      : 'weather',
            originalId: e['id']?.toString(),
            idScheme  : 'eonet',
            confidence: 0.9,
            sourceUrl : sourceUrl,
            updated   : null,
        ],
        properties    : [
            title    : e['title'],
            category : category,
            wxtype   : typeLabel,
            icon     : icon,
            severity : severity,
            date     : eventDate,
            eventSrc : eventSource,
            provider : 'NASA EONET',
        ],
    ])

    // ── Volcano dual-emit: FIRE entity for the fires layer (brightness-500 marker) ──
    if (category == 'volcanoes') {
        emit([
            id            : "eonet-volc-${e['id']}".toString(),
            name          : "[VOLCANO] ${e['title']}".toString(),
            domain        : 'LAND',
            entityType    : 'FIRE',
            subtype       : 'volcano',
            position      : [lat: lat, lng: lng, alt: null],
            threat        : 'NONE',
            classification: 'UNCLASSIFIED',
            releasability : null,
        releasability : null,
            confidence    : 0.9,
            timestamp     : eventDate,
            source        : [
                provider  : 'NASA-EONET',
                feed      : 'fires',
                originalId: e['id']?.toString(),
                idScheme  : 'eonet',
                confidence: 0.9,
                sourceUrl : sourceUrl,
                updated   : null,
            ],
            properties    : [
                brightness: 500,                       // route.ts volcano constants
                confidence: 'high',
                frp       : 100,
                date      : eventDate?.toString()?.split('T')[0],
                time      : '',
                firetype  : 'volcano',
                title     : "[VOLCANO] ${e['title']}".toString(),
                sourceName: 'NASA-EONET',
            ],
        ])
    }
}

if (emitted == 0) {
    log.warn('No weather/volcano entities emitted from EONET payload')
    session.transfer(flowFile, REL_FAILURE)
} else {
    log.info("Emitted ${emitted} EONET entities to Kafka path")
    session.remove(flowFile)
}