// Replays raw upstream responses through a NiFi ExecuteScript transform, outside NiFi
// (burndown 17.6: rebuilding events from the bronze table).
//
//   java -cp groovy.jar:groovy-json.jar groovy.ui.GroovyMain Replay.groovy <script.groovy> <in.jsonl> <out.jsonl>
//
// <in.jsonl>: one response per line, oldest first:
//   {"received_ms": 1763660000000, "attrs": {"invokehttp.request.url": "..."}, "body": "..."}
// <out.jsonl>: every FlowFile the script sends to success, one per line.
//
// What makes a replay match the live flow:
//   * The clock: the scripts stamp captured_at (and hormuz.now its heartbeat) with
//     Instant.now(). Here Instant.now() is each response's received time, so a rebuilt
//     row says when the response arrived, not when the rebuild ran.
//   * State: responses run in order through one script instance with one state map,
//     as in NiFi (hormuz.now keeps each vessel's last position).
//   * The script itself is compiled once, then run per response.
// Plain Groovy 4 and Java 8+, with no NiFi jars: the session, state and log are mocks.

import groovy.json.JsonSlurper

interface OutputStreamCallback { void process(OutputStream out) }
enum Scope { LOCAL, CLUSTER }

class FF {
    Map<String, String> attrs = [:]
    byte[] content = new byte[0]
    String getAttribute(String k) { attrs[k] }
}

class StateMap {
    Map<String, String> m
    Map<String, String> toMap() { m }
}

class Session {
    FF input
    List<FF> success = [], failure = []
    FF get() { def f = input; input = null; f }
    InputStream read(FF f) { new ByteArrayInputStream(f.content) }
    FF create(FF parent) { new FF(attrs: new LinkedHashMap(parent.attrs)) }
    FF write(FF f, OutputStreamCallback cb) { def b = new ByteArrayOutputStream(); cb.process(b); f.content = b.toByteArray(); f }
    FF putAttribute(FF f, String k, String v) { f.attrs[k] = v; f }
    void transfer(FF f, Object rel) { (rel == 'success' ? success : failure) << f }
    void remove(FF f) { }
}

class State {
    Map<String, String> saved = [:]
    StateMap getState(Scope s) { new StateMap(m: saved) }
    void setState(Map m, Scope s) { saved = new LinkedHashMap(m) }
}

def (scriptPath, inPath, outPath) = args[0..2]
def runId = args.size() > 3 ? args[3] : 'rebuild'

def text = new File(scriptPath).text
    .replace('import org.apache.commons.io.IOUtils', '')
    .replace('import org.apache.nifi.components.state.Scope', '')
    .replace('Instant.now()', 'Instant.ofEpochMilli(__nowMs as long)')
// Any other clock would stamp the rebuild's time on the rows.
['System.currentTimeMillis', 'new Date()', 'LocalDateTime.now', 'OffsetDateTime.now', 'ZonedDateTime.now'].each { c ->
    if (text.contains(c)) {
        System.err.println("Replay: ${new File(scriptPath).name} reads the clock with ${c}; replace it with Instant.now()")
        System.exit(2)
    }
}

def state = new State()
def counts = [responses: 0, success: 0, failure: 0, errors: 0]
def shell = new GroovyShell(this.class.classLoader)
def script = shell.parse(text, new File(scriptPath).name)
def slurper = new JsonSlurper()
new File(outPath).withWriter('UTF-8') { w ->
    new File(inPath).eachLine('UTF-8') { line ->
        if (!line.trim()) return
        def rec = slurper.parseText(line)
        def attrs = new LinkedHashMap((rec.attrs ?: [:]).findAll { k, v -> v != null }.collectEntries { k, v -> [(k): v.toString()] })
        attrs['ingest.run.id'] = runId
        def session = new Session(input: new FF(attrs: attrs, content: (rec.body ?: '').getBytes('UTF-8')))
        def log = [info: { m -> }, warn: { m -> }, error: { m -> System.err.println("  script error: $m") }]
        script.binding = new Binding(session: session, log: log, REL_SUCCESS: 'success', REL_FAILURE: 'failure',
                                     context: [stateManager: state], __nowMs: rec.received_ms)
        counts.responses++
        try {
            script.run()
        } catch (Throwable t) {
            counts.errors++
            System.err.println("  response at ${rec.received_ms}: ${t.class.simpleName}: ${t.message}")
        }
        session.success.each { f -> w << new String(f.content, 'UTF-8') << '\n' }
        counts.success += session.success.size()
        counts.failure += session.failure.size()
    }
}
println "replay: ${counts.responses} responses -> ${counts.success} envelopes, ${counts.failure} to failure, ${counts.errors} errors"
