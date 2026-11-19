/**
 * NiFi ExecuteScript — USGS earthquakes -> canonical horus-events Kafka messages.
 *
 * Input:  FlowFile body = raw USGS GeoJSON from InvokeHTTP
 * Output: One FlowFile per entity (JSON envelope matching flink/sql/kafka_to_lakehouse.sql)
 *
 * Script path inside container: /opt/nifi/conf/horus/scripts/earthquakes-ingest.groovy
 *
 * PROVENANCE UPDATE:
 *   - Adds a per-entity trace_id (UUID) to the envelope AND as a flowfile attribute,
 *     giving an unbroken thread: Iceberg row -> trace_id -> NiFi provenance -> Kafka header.
 *   - Sets source.provider to the true origin ('USGS'), not the Horus platform.
 *   - Captures the source request URL (from the upstream InvokeHTTP attribute) when present.
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
def geojson = slurper.parseText(raw)
 
// ── transform (usgs-earthquakes.groovy inlined for NiFi classloader simplicity) ──
def features = geojson?.features ?: []
def earthquakes = features.collect { f ->
    def coords = f?.geometry?.coordinates ?: [0, 0, 0]
    //def props = f?.properties ?: [:]
    def props = (f?.get('properties')) ?: [:]
    [
        id       : f.id,
        lat      : coords.size() > 1 ? coords[1] : null,
        lng      : coords.size() > 0 ? coords[0] : null,
        depth    : coords.size() > 2 ? coords[2] : null,
        magnitude: props.mag,
        place    : props.place,
        time     : props.time,
        url      : props.url,
        tsunami  : props.tsunami,
        type     : props.type,
        felt     : props.felt,
        alert    : props.alert,
        updated  : props.updated,   // source-side last-modified (provenance)
    ]
}
 
def capturedAt = Instant.now().atOffset(ZoneOffset.UTC)
    .format(DateTimeFormatter.ofPattern("yyyy-MM-dd'T'HH:mm:ss'Z'"))
def ingestRunId = flowFile.getAttribute('ingest.run.id') ?: ('nifi-' + UUID.randomUUID().toString().take(12))
 
// Provenance: the true data origin, the specific feed, and (if InvokeHTTP set it) the request URL.
def provider  = 'USGS'
def feed      = 'earthquakes'
def sourceUrl = flowFile.getAttribute('invokehttp.request.url') ?: 'https://earthquake.usgs.gov'
def emitted   = 0
 
earthquakes.each { item ->
    if (item.lat == null || item.lng == null) return
 
    // Per-observation correlation id — the thread that ties this row across the whole pipeline.
    def traceId = UUID.randomUUID().toString()
 
    def eventTime = item.time ? Instant.ofEpochMilli(item.time as Long).atOffset(ZoneOffset.UTC)
        .format(DateTimeFormatter.ofPattern("yyyy-MM-dd'T'HH:mm:ss'Z'")) : capturedAt
 
    def entity = [
        id            : item.id?.toString(),
        name          : item.place?.toString() ?: item.id?.toString(),
        domain        : 'LAND',
        entityType    : 'SEISMIC',
        subtype       : item.type?.toString(),   // earthquake, quarry blast, ...
        position      : [
            lat: item.lat as Double,
            lng: item.lng as Double,
            alt: null,   // depth is not altitude: it stays in properties.depth (km)
        ],
        threat        : 'NONE',
        classification: 'UNCLASSIFIED',
        releasability : null,
        confidence    : 0.9,
        timestamp     : eventTime,
        source        : [
            provider  : provider,          // was the platform name — now the true origin (USGS)
            feed      : feed,
            originalId: item.id?.toString(),
            idScheme  : 'usgs',
            confidence: 0.9,
            sourceUrl : sourceUrl,         // where this record was fetched from
            updated   : item.updated,      // source-asserted last-modified epoch ms
        ],
        properties    : [
            mag    : item.magnitude,
            depth  : item.depth,
            url    : item.url,
            tsunami: item.tsunami,
            alert  : item.alert,
            felt   : item.felt,
        ],
    ]
 
    def envelope = [
        schema_version: 2,
        trace_id      : traceId,           // NEW: top-level correlation id -> events_iceberg.trace_id
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
    out = session.putAttribute(out, 'trace.id', traceId)   // NEW: attribute for NiFi provenance / Kafka header
    session.transfer(out, REL_SUCCESS)
    emitted++
}
 
if (emitted == 0) {
    log.warn('No earthquake entities emitted from USGS payload')
    session.transfer(flowFile, REL_FAILURE)
} else {
    log.info("Emitted ${emitted} earthquake entities to Kafka path")
    session.remove(flowFile)
}