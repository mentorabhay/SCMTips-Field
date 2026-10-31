package com.scmtips.field.app

import android.app.Activity
import android.content.Context
import android.os.Build
import androidx.security.crypto.EncryptedSharedPreferences
import androidx.security.crypto.MasterKey
import com.scmtips.field.app.assistant.AssistantClient
import com.scmtips.field.app.assistant.AssistantOutcome
import com.scmtips.field.app.assistant.SiteModes
import com.scmtips.field.app.device.BarcodeReader
import com.scmtips.field.app.device.ContinuousSpeech
import com.scmtips.field.app.device.PhoneLocation
import com.scmtips.field.app.device.PhoneSpeech
import com.scmtips.field.app.device.TtsSpeaker
import com.scmtips.field.app.glasses.DatGlasses
import com.scmtips.field.app.glasses.GlassesAdvice
import com.scmtips.field.app.glasses.GlassesHelp
import com.scmtips.field.app.glasses.GlassesStatus
import com.scmtips.field.app.home.Link
import com.scmtips.field.app.home.Person
import com.scmtips.field.app.home.TodayModel
import com.scmtips.field.app.jobs.Command
import com.scmtips.field.app.jobs.InputSource
import com.scmtips.field.app.jobs.JobAction
import com.scmtips.field.app.jobs.JobGrammar
import com.scmtips.field.app.jobs.JobRequests
import com.scmtips.field.app.jobs.JobRunner
import com.scmtips.field.app.jobs.JobState
import com.scmtips.field.app.jobs.JobTask
import com.scmtips.field.app.jobs.UnknownCodeHandler
import com.scmtips.field.app.jobs.JobType
import com.scmtips.field.app.jobs.Practice
import com.scmtips.field.app.jobs.PracticeTransport
import com.scmtips.field.app.jobs.ScanLookup
import com.scmtips.field.app.jobs.ScanResult
import com.scmtips.field.app.jobs.ScannerKind
import com.scmtips.field.app.jobs.StepView
import com.scmtips.field.app.navigation.Screen
import com.scmtips.field.app.net.FieldSession
import com.scmtips.field.app.net.HttpError
import com.scmtips.field.app.net.PhoneBinding
import com.scmtips.field.app.scan.FrameScanFilter
import com.scmtips.field.app.scan.Yuv
import com.scmtips.field.app.session.AssistantPort
import com.scmtips.field.app.session.Conductor
import com.scmtips.field.app.session.JobDesk
import com.scmtips.field.app.session.MicPlan
import com.scmtips.field.app.session.MicSource
import com.scmtips.field.app.session.Photo
import com.scmtips.field.app.session.SessionChange
import com.scmtips.field.app.session.SessionView
import com.scmtips.field.app.session.TurnSpeaker
import com.scmtips.field.app.session.WorkSession
import com.scmtips.field.app.session.WorkSessionService
import com.scmtips.field.app.slice.Pairing
import com.scmtips.field.app.slice.PairingPayload
import com.scmtips.field.core.common.UUIDv7
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.Job
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.MutableSharedFlow
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.SharedFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asSharedFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.isActive
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.contentOrNull
import java.io.File
import java.io.IOException
import java.util.UUID
import java.util.concurrent.atomic.AtomicBoolean

data class AppUi(
    val pairing: Pairing? = null,
    val deviceId: String? = null,
    val person: Person = Person.UNKNOWN,
    val tab: Screen = Screen.Today,
    val tasks: List<JobTask> = emptyList(),
    val loading: Boolean = false,
    val link: Link = Link.CONNECTING,
    val connecting: Boolean = false,
    val connectError: String? = null,
    val job: StepView? = null,
    val scanner: ScannerKind = ScannerKind.CAMERA,
    val audioOnly: Boolean = false,
    val glassesSpeech: Boolean = true,
    val glasses: GlassesStatus = GlassesStatus(),
    val glassesAdvice: GlassesAdvice = GlassesHelp.advise(GlassesStatus(), null),
    val visitId: String? = null,
    /** The site the open visit is at; a job at another site checks in again. */
    val visitSiteId: String? = null,
    val scanResult: ScanResult? = null,
    val toast: String? = null,
    val log: List<String> = emptyList(),
    /** The M3 work session (glasses first): listening / paused / camera, last words heard and said. */
    val work: SessionView = SessionView(),
)

/**
 * Wires the pure [JobRunner] to the real world: field-api over HTTP ([FieldSession]), live events, the
 * three scanners (phone camera via MainActivity, handheld wedge keys, glasses photo + ML Kit), speech in
 * (glasses or phone mic) through [JobGrammar], speech out ([TtsSpeaker]), location for tower check-in.
 *
 * M3 (glasses first, docs/design/M3_CONTRACT.md §5): a work session ([WorkSession], foreground
 * [WorkSessionService]) listens continuously through the glasses and routes words through the pure
 * [Conductor] (grammar first, then the Field Assistant); the glasses' video frames are decoded on the
 * phone for scan by looking ([FrameScanFilter]). The wiring here stays thin; the rules are in the pure
 * classes and their JVM tests.
 */
class FieldController(private val context: Context, private val toolkitError: () -> String?) {
    private val scope = CoroutineScope(SupervisorJob() + Dispatchers.Main.immediate)
    private val _ui = MutableStateFlow(AppUi())
    val ui: StateFlow<AppUi> = _ui.asStateFlow()

    /** MainActivity opens the phone camera scanner when this fires. */
    private val _cameraRequests = MutableSharedFlow<Unit>(extraBufferCapacity = 1)
    val cameraRequests: SharedFlow<Unit> = _cameraRequests.asSharedFlow()

    private val prefs by lazy {
        val key = MasterKey.Builder(context).setKeyScheme(MasterKey.KeyScheme.AES256_GCM).build()
        EncryptedSharedPreferences.create(
            context, "scmtips-field-slice", key,
            EncryptedSharedPreferences.PrefKeyEncryptionScheme.AES256_SIV,
            EncryptedSharedPreferences.PrefValueEncryptionScheme.AES256_GCM,
        )
    }
    private val binding by lazy {
        PhoneBinding(object : PhoneBinding.Store {
            override fun get(key: String): String? = prefs.getString(key, null)
            override fun put(key: String, value: String) = prefs.edit().putString(key, value).apply()
            override fun remove(key: String) = prefs.edit().remove(key).apply()
        }) { UUID.randomUUID().toString() }
    }
    private val workSession = WorkSession { v -> _ui.value = _ui.value.copy(work = v) }
    private val tts = TtsSpeaker(context, { said -> log("🔊 $said") }, { on -> scope.launch { workSession.speaking(on); applyHold() } })
    private val speaker = TurnSpeaker(tts)
    private val barcodes = BarcodeReader()
    private val phoneSpeech = PhoneSpeech(context, { t, c -> onSpeech(t, c, "phone") }, { e -> log("mic: $e") })
    private val continuous = ContinuousSpeech(context, scope, { t, c -> onSpeech(t, c, "session") }, { e -> log("mic: $e") })
    private val location = PhoneLocation(context) { lat, lon, acc, at -> runnerAct(JobAction.Location(lat, lon, acc, at)) }
    val glasses = DatGlasses(
        scope,
        onCaptureButton = { captureWithGlasses() },
        onTranscript = { t, c -> onSpeech(t, c, "glasses") },
        onFrame = ::onFrame,
    )
    private val frames = FrameScanFilter()
    private val frameBusy = AtomicBoolean(false)
    private var assistant: AssistantClient? = null
    private var siteModes: SiteModes? = null
    private var lastGlassesSession = "none"
    private var autoStarted = false

    /** MainActivity sets this: the session starts by itself only while the app is on screen. */
    @Volatile var inForeground = false

    private val desk = object : JobDesk {
        override val jobOpen: Boolean get() = runner != null
        override val jobState: JobState get() = runner?.state ?: JobState(null, null, null)
        override fun tasks(): List<JobTask> = _ui.value.tasks

        override suspend fun act(a: JobAction) {
            val r = runner ?: return
            try {
                r.act(a)
            } catch (e: Exception) {
                log("⚠ ${describe(e)}")
            }
        }

        override suspend fun openTask(taskId: String): Boolean {
            if (_ui.value.tasks.none { it.id == taskId }) refreshTasksNow()
            if (_ui.value.tasks.none { it.id == taskId }) return false
            this@FieldController.openTask(taskId)
            return true
        }

        override suspend fun refreshTask(taskId: String, focusCode: String?) {
            refreshTasksNow()
            val fresh = _ui.value.tasks.firstOrNull { it.id == taskId } ?: return
            val r = runner
            when {
                r != null && r.task.id == taskId -> r.updateTask(fresh, focusCode)
                r == null -> { this@FieldController.openTask(taskId); focusCode?.let { runner?.act(JobAction.Scanned(it)) } }
            }
        }

        /** "capture" said aloud: the glasses camera when they are connected (phone in the pocket), else the chosen scanner. */
        override suspend fun capture() = if (glasses.status.value.session == "STARTED") captureWithGlasses() else requestScan()

        override suspend fun photo(): Photo? {
            if (glasses.status.value.session != "STARTED") return null
            val bmp = glasses.capturePhoto() ?: return null
            val codes = barcodes.read(bmp)
            val b64 = withContext(Dispatchers.Default) { BarcodeReader.jpegBase64(bmp) }
            return Photo(codes, b64)
        }
    }

    private val conductor = Conductor(
        siteId = { _ui.value.pairing?.siteId },
        desk = desk,
        assistant = AssistantPort { t -> assistant?.turn(t) ?: AssistantOutcome.Failed("not connected to the PC") },
        speaker = speaker,
        session = workSession,
        onStopWork = { stopWork() },
        log = ::log,
    )

    /** Sandbox sites only, during a work session: an unknown code goes to the assistant with a photo. */
    private val unknownCodes = UnknownCodeHandler { task, code ->
        val site = task.siteId ?: _ui.value.pairing?.siteId
        val modes = siteModes
        if (!workSession.view.active || site == null || modes == null || !modes.allowsNewItems(site, code)) {
            false
        } else {
            scope.launch { conductor.unknownCode(code) }
            true
        }
    }

    private var session: FieldSession? = null
    private var runner: JobRunner? = null
    private var runnerJobs = mutableListOf<Job>()
    private var loops: Job? = null
    private var lastEventId: String? = null

    /** True while the manual code field has focus, so typed keys are not taken as a handheld scan. */
    @Volatile var manualEntryOpen = false

    init {
        scope.launch {
            glasses.status.collect { g ->
                _ui.value = _ui.value.copy(glasses = g, glassesAdvice = GlassesHelp.advise(g, toolkitError()))
                onGlassesStatus(g)
            }
        }
        val scanner = prefs.getString(KEY_SCANNER, null)?.let { s -> ScannerKind.entries.firstOrNull { it.name == s } } ?: ScannerKind.CAMERA
        _ui.value = _ui.value.copy(
            scanner = scanner,
            audioOnly = prefs.getBoolean(KEY_AUDIO_ONLY, false),
            glassesSpeech = prefs.getBoolean(KEY_GLASSES_SPEECH, true),
            visitId = prefs.getString(KEY_VISIT, null),
            visitSiteId = prefs.getString(KEY_VISIT_SITE, null),
            glassesAdvice = GlassesHelp.advise(GlassesStatus(), toolkitError()),
        )
        prefs.getString(KEY_PAIRING, null)?.let { saved ->
            runCatching { PairingPayload.parse(saved) }.onSuccess { p -> attach(p, fromScan = false) }
        }
    }

    // --- connect (pairing) -------------------------------------------------------------------

    fun pair(qrText: String) {
        val p = try {
            PairingPayload.parse(qrText)
        } catch (e: IllegalArgumentException) {
            _ui.value = _ui.value.copy(connectError = e.message ?: "That code is not a SCMTips pairing code.")
            return
        }
        // The device id is kept when the code is for the same PC and company (PhoneBinding).
        prefs.edit().putString(KEY_PAIRING, qrText).apply()
        attach(p, fromScan = true)
    }

    /** Connect screen "Try again": the saved code, registered again. */
    fun retryConnect() {
        val p = _ui.value.pairing ?: return
        attach(p, fromScan = true)
    }

    fun unpair() {
        stopWork()
        loops?.cancel()
        closeJob(null)
        glasses.disconnect()
        // The device id stays: re-pairing to another site of the same PC reuses it (PhoneBinding scope).
        prefs.edit().remove(KEY_PAIRING).remove(KEY_VISIT).remove(KEY_VISIT_SITE).apply()
        session = null
        _ui.value = AppUi(
            scanner = _ui.value.scanner, audioOnly = _ui.value.audioOnly, glassesSpeech = _ui.value.glassesSpeech,
            glasses = _ui.value.glasses, glassesAdvice = _ui.value.glassesAdvice, log = _ui.value.log,
        )
    }

    private fun attach(p: Pairing, fromScan: Boolean) {
        val where = PhoneBinding.scope(p.apiBaseUrl, p.tenantId)
        val deviceId = binding.savedDevice(where)
        val s = FieldSession(p.apiBaseUrl, p.coreToken, deviceId)
        session = s
        assistant = AssistantClient(s) { UUIDv7.generate() }
        siteModes = SiteModes(s)
        _ui.value = _ui.value.copy(pairing = p, deviceId = deviceId, person = Person.fromCoreToken(p.coreToken), connecting = true, connectError = null)
        val api = object : PhoneBinding.Api {
            override suspend fun exchange(deviceId: String?) = s.bind(deviceId)
            override suspend fun register(serial: String, idempotencyKey: String) = s.registerPhone(
                serial = serial,
                model = "${Build.MANUFACTURER} ${Build.MODEL}",
                osVersion = "Android ${Build.VERSION.RELEASE}",
                appVersion = BuildConfig.VERSION_NAME,
                idempotencyKey = idempotencyKey,
            )
        }
        scope.launch {
            try {
                val id = binding.connect(where, fromScan, api)
                _ui.value = _ui.value.copy(deviceId = id, connecting = false, link = Link.ONLINE)
                log("Connected to ${p.siteName}; phone device $id")
                startLoops(s)
                refreshTasks()
            } catch (e: Exception) {
                val why = describe(e)
                log("⚠ $why")
                _ui.value = _ui.value.copy(connecting = false, connectError = why,
                    link = if (e is IOException) Link.OFFLINE else _ui.value.link)
                if (e is IOException && _ui.value.deviceId != null) startLoops(s) // known phone: keep trying
            }
        }
    }

    // --- Today ---------------------------------------------------------------------------------

    fun selectTab(t: Screen) {
        _ui.value = _ui.value.copy(tab = t, scanResult = if (t == Screen.Scan) _ui.value.scanResult else null)
    }

    fun refreshTasks() {
        scope.launch { refreshTasksNow() }
    }

    private suspend fun refreshTasksNow() {
        val s = session ?: return
        val site = _ui.value.pairing?.siteId ?: return
        _ui.value = _ui.value.copy(loading = true)
        try {
            _ui.value = _ui.value.copy(tasks = s.tasks(site), link = Link.ONLINE)
        } catch (e: Exception) {
            log("⚠ tasks: ${describe(e)}")
            _ui.value = _ui.value.copy(link = if (e is IOException) Link.OFFLINE else _ui.value.link,
                toast = if (e is IOException) null else describe(e))
        } finally {
            _ui.value = _ui.value.copy(loading = false)
        }
    }

    fun openTask(taskId: String) {
        val t = _ui.value.tasks.firstOrNull { it.id == taskId } ?: return toast("That job is no longer open.")
        val s = session ?: return
        val siteLabel = if (t.type.isTower) t.title.substringBefore(" · ") else _ui.value.pairing?.siteName ?: "the site"
        val site = t.siteId ?: _ui.value.pairing?.siteId
        val visit = _ui.value.visitId?.takeIf { _ui.value.visitSiteId == null || _ui.value.visitSiteId == site }
        startRunner(JobRunner(
            t, s, speaker, _ui.value.deviceId, visitId = visit, siteId = site,
            siteLabel = siteLabel, scanner = _ui.value.scanner, nextSeq = ::nextClimbSeq, unknownCodes = unknownCodes,
        ))
    }

    fun openStarter(type: JobType) {
        val id = TodayModel.starters(_ui.value.tasks).firstOrNull { it.type == type }?.taskId
        if (id == null) toast(TodayModel.noneOpen(type)) else openTask(id)
    }

    fun startPractice() {
        startRunner(JobRunner(Practice.task, PracticeTransport(), speaker, deviceId = "practice", practice = true, scanner = _ui.value.scanner))
    }

    private fun startRunner(r: JobRunner) {
        closeJob(null)
        runner = r
        var toldDone = false
        runnerJobs += scope.launch {
            r.view.collect { v ->
                _ui.value = _ui.value.copy(job = v)
                syncVisit(r)
                if (r.isDone && !toldDone && !r.practice && workSession.view.active) {
                    toldDone = true
                    scope.launch { conductor.stepDone() }
                }
                if (v.finished) closeJob(v.exitNote)
            }
        }
        runnerJobs += scope.launch { while (isActive) { r.tick(); delay(1_000) } }
        frames.reset()
        applyStreaming()
        r.start()
    }

    private fun closeJob(note: String?) {
        val r = runner ?: return
        syncVisit(r)
        runner = null
        location.stop()
        runnerJobs.forEach { it.cancel() }
        runnerJobs.clear()
        _ui.value = _ui.value.copy(job = null, toast = note ?: _ui.value.toast)
        applyStreaming()
        if (!r.practice) refreshTasks()
    }

    private fun syncVisit(r: JobRunner) {
        if (r.practice || !r.task.type.isTower || r.visitId == _ui.value.visitId) return
        val site = r.visitId?.let { r.task.siteId ?: _ui.value.pairing?.siteId }
        prefs.edit().apply {
            if (r.visitId != null) putString(KEY_VISIT, r.visitId).putString(KEY_VISIT_SITE, site) else remove(KEY_VISIT).remove(KEY_VISIT_SITE)
        }.apply()
        _ui.value = _ui.value.copy(visitId = r.visitId, visitSiteId = site)
    }

    fun jobAction(a: JobAction) = runnerAct(a)

    private fun runnerAct(a: JobAction) {
        val r = runner ?: return
        scope.launch {
            try {
                r.act(a)
            } catch (e: Exception) {
                log("⚠ ${describe(e)}")
                toast(describe(e))
            }
        }
    }

    /** The check-in step needs location; MainActivity asks for the permission first. */
    fun startLocation(): Boolean = location.start()
    fun stopLocation() = location.stop()

    // --- scanning ------------------------------------------------------------------------------

    /** The big scan area, or "capture" said aloud: use the chosen scanner. */
    fun requestScan() {
        when (_ui.value.scanner) {
            ScannerKind.CAMERA -> _cameraRequests.tryEmit(Unit)
            ScannerKind.GLASSES -> captureWithGlasses()
            ScannerKind.HANDHELD -> toast("Pull the trigger on your scanner.")
        }
    }

    /** Key events become a handheld scan only while a code is wanted. */
    val wantsWedge: Boolean
        get() = _ui.value.scanner == ScannerKind.HANDHELD && !manualEntryOpen && _ui.value.pairing != null &&
            (runner != null || _ui.value.tab == Screen.Scan)

    fun onCode(raw: String, source: InputSource = InputSource.SCAN) {
        val code = raw.trim()
        if (code.isEmpty()) return
        log("scan: $code")
        val r = runner
        if (r != null) {
            runnerAct(JobAction.Scanned(code, source))
        } else {
            _ui.value = _ui.value.copy(tab = Screen.Scan, scanResult = ScanLookup.lookup(code, _ui.value.tasks))
            if (workSession.view.active) scope.launch { conductor.scannedOutsideJob(code) }
        }
    }

    private fun captureWithGlasses() {
        scope.launch {
            val photo = glasses.capturePhoto() ?: run {
                log("No photo from the glasses (see Me → Smart glasses)")
                speaker.earcon(com.scmtips.field.core.wearables.EarconCue.ERROR)
                speaker.say("No photo from the glasses. Use the phone.")
                return@launch
            }
            val codes = barcodes.read(photo)
            log("photo ${photo.width}x${photo.height}: ${if (codes.isEmpty()) "no barcode" else codes.joinToString()}")
            if (codes.isEmpty()) {
                speaker.earcon(com.scmtips.field.core.wearables.EarconCue.ERROR)
                speaker.say("No barcode seen. Try again, closer.")
            } else {
                onCode(runner?.bestOf(codes) ?: codes.first())
            }
        }
    }

    // --- speech --------------------------------------------------------------------------------

    /** Hold to talk: the phone fallback outside a work session (in a session the microphone is already open). */
    fun talkStart() {
        if (workSession.view.active) toast("The work session is listening already. Just speak.") else phoneSpeech.start()
    }

    fun talkStop() {
        if (!workSession.view.active) phoneSpeech.stop()
    }

    private fun onSpeech(text: String, confidence: Float, source: String) {
        val w = workSession.view
        if (w.active) {
            if (!w.listening) return // paused, or our own prompt heard back: never acted on
            log("🎤 [$source ${"%.2f".format(java.util.Locale.ROOT, confidence)}] $text")
            scope.launch { log("→ ${conductor.heard(text, confidence).name.lowercase()}") }
            return
        }
        if (source != "phone") return // no session: only the operator's own hold-to-talk is heard (A-03)
        log("🎤 [$source ${"%.2f".format(java.util.Locale.ROOT, confidence)}] $text")
        if (JobGrammar.parse(text, confidence) == Command.Capture) requestScan()
        if (runner != null) runnerAct(JobAction.Heard(text, confidence))
    }

    // --- work session (M3 §5) ------------------------------------------------------------------

    /** "Start work" on Today (MainActivity asks for the microphone first), or the glasses connecting. */
    fun startWork() {
        if (_ui.value.pairing == null || _ui.value.deviceId == null) return toast("Connect this phone to the PC first.")
        if (workSession.start(MicSource.NONE, glasses.status.value.session == "STARTED") == null) return
        WorkSessionService.start(context)
        log("work session started")
        frames.reset()
        applyMic()
        applyStreaming()
        val site = _ui.value.pairing?.siteId
        scope.launch {
            if (site != null) siteModes?.prime(site)
            conductor.start()
        }
    }

    fun stopWork() {
        if (workSession.stop() == null) return
        log("work session stopped")
        continuous.stop()
        glasses.setListening(false)
        glasses.framesWanted = false
        tts.useCallAudio(false)
        applyStreaming()
        scope.launch {
            conductor.end()
            assistant?.reset()
        }
    }

    fun pauseWork() {
        if (workSession.pauseByOperator() != null) { applyHold(); scope.launch { conductor.paused() } }
    }

    fun resumeWork() {
        if (workSession.resumeByOperator() != null) { applyMic(); scope.launch { conductor.resumed() } }
    }

    /** WorkSessionService could not go to the foreground: no session without its notification. */
    fun workServiceFailed(why: String) {
        log("⚠ work session: $why")
        stopWork()
        toast(why)
    }

    fun dismissWorkOffer() = workSession.dismissOffer()

    private fun onGlassesStatus(g: com.scmtips.field.app.glasses.GlassesStatus) {
        val was = lastGlassesSession
        lastGlassesSession = g.session
        workSession.camera(g.cameraOn)
        if (g.session != was) {
            if (g.session == "STOPPED" || g.session == "none" || g.session == "IDLE") autoStarted = false
            when (workSession.onGlasses(g.session)) {
                is SessionChange.Paused -> { applyHold(); scope.launch { conductor.paused() } }
                SessionChange.Resumed -> { applyMic(); scope.launch { conductor.resumed() } }
                else -> Unit
            }
            // Glasses just connected (not a resume after a pause): start the session by itself, once per connection.
            if (g.session == "STARTED" && was != "PAUSED" && !workSession.view.active && !autoStarted && inForeground &&
                _ui.value.deviceId != null
            ) {
                autoStarted = true
                startWork()
            }
        }
        // Toolkit speech refused or failing during a session: move to the phone's recogniser (and back).
        if (workSession.view.active) {
            val wantDat = MicPlan.useGlassesSpeech(_ui.value.glassesSpeech, g.speech)
            if (wantDat != (workSession.view.mic == MicSource.GLASSES)) applyMic()
        }
    }

    private fun applyMic() {
        val v = workSession.view
        if (!v.active) return
        if (MicPlan.useGlassesSpeech(_ui.value.glassesSpeech, glasses.status.value.speech)) {
            continuous.stop()
            tts.useCallAudio(false)
            glasses.setListening(true)
            workSession.mic(MicSource.GLASSES)
        } else {
            glasses.setListening(false)
            val src = continuous.start(preferBluetooth = true)
            tts.useCallAudio(src == MicSource.BLUETOOTH)
            workSession.mic(src)
        }
        applyHold()
    }

    /** The microphone is held while the phone speaks or the session is paused; frames only while not paused. */
    private fun applyHold() {
        val v = workSession.view
        continuous.hold(!v.listening)
        glasses.framesWanted = v.active && v.paused == null
        if (!glasses.framesWanted) frames.reset()
    }

    /** The glasses' camera streams during a work session, or while a job scans with the glasses. */
    private fun applyStreaming() {
        glasses.setStreaming(workSession.view.active || (runner != null && _ui.value.scanner == ScannerKind.GLASSES))
    }

    /** One glasses video frame (I420): decoded off the main thread, one at a time; busy frames are dropped. */
    private fun onFrame(i420: ByteArray, width: Int, height: Int) {
        if (!glasses.framesWanted || !frameBusy.compareAndSet(false, true)) return
        scope.launch(Dispatchers.Default) {
            try {
                val nv21 = Yuv.i420ToNv21(i420, width, height)
                val codes = if (nv21 == null) emptyList() else barcodes.readNv21(nv21, width, height)
                val scans = frames.onFrame(codes, System.currentTimeMillis())
                if (scans.isNotEmpty()) withContext(Dispatchers.Main) { onLookScan(scans) }
            } finally {
                frameBusy.set(false)
            }
        }
    }

    /** A code held in view for two frames: a scan for the open job's scan step, or for the assistant. */
    private fun onLookScan(codes: List<String>) {
        if (!workSession.view.active || workSession.view.paused != null) return
        val r = runner
        when {
            r == null -> onCode(codes.first())
            r.isScanStep -> onCode(r.bestOf(codes) ?: codes.first())
            else -> Unit // not a scan step: codes seen in passing are ignored
        }
    }

    // --- Me ------------------------------------------------------------------------------------

    fun cycleScanner() {
        val all = ScannerKind.entries
        val next = all[(all.indexOf(_ui.value.scanner) + 1) % all.size]
        prefs.edit().putString(KEY_SCANNER, next.name).apply()
        runner?.scanner = next
        _ui.value = _ui.value.copy(scanner = next)
        applyStreaming()
    }

    fun toggleAudioOnly() {
        val on = !_ui.value.audioOnly
        prefs.edit().putBoolean(KEY_AUDIO_ONLY, on).apply()
        _ui.value = _ui.value.copy(audioOnly = on)
    }

    fun toggleGlassesSpeech() {
        val on = !_ui.value.glassesSpeech
        prefs.edit().putBoolean(KEY_GLASSES_SPEECH, on).apply()
        _ui.value = _ui.value.copy(glassesSpeech = on)
        applyMic()
    }

    fun glassesSetUp(activity: Activity) {
        glasses.startMonitoring()
        when (_ui.value.glassesAdvice.action) {
            GlassesAdvice.Action.REGISTER -> glasses.register(activity)
            else -> Unit // CONNECT goes through MainActivity (glasses camera/mic permissions first)
        }
    }

    fun connectGlasses() {
        glasses.startMonitoring()
        glasses.connect(withSpeech = _ui.value.glassesSpeech)
    }

    /** Writes the feedback report (app, phone, glasses, last log lines) and returns it for sharing. */
    fun feedbackReport(): String {
        val u = _ui.value
        val text = buildString {
            appendLine("SCMTips Field ${BuildConfig.VERSION_NAME} feedback")
            appendLine("Phone: ${Build.MANUFACTURER} ${Build.MODEL}, Android ${Build.VERSION.RELEASE}")
            appendLine("Connected to: ${u.pairing?.siteName ?: "not connected"} (${u.pairing?.apiBaseUrl ?: "-"})")
            appendLine("Scanner: ${u.scanner.label}; audio-only: ${u.audioOnly}")
            appendLine("Glasses: ${u.glassesAdvice.text} [${u.glasses}]")
            appendLine("Work session: ${u.work.stateText}; assistant ${u.work.assistantOnline ?: "not asked yet"}")
            toolkitError()?.let { appendLine("Glasses toolkit: $it") }
            appendLine()
            appendLine("What is hard? (write here)")
            appendLine()
            appendLine("--- last ${u.log.size} log lines ---")
            u.log.forEach { appendLine(it) }
        }
        runCatching {
            val dir = File(context.filesDir, "feedback").apply { mkdirs() }
            File(dir, "feedback-${System.currentTimeMillis()}.txt").writeText(text)
        }
        return text
    }

    fun toast(text: String?) {
        _ui.value = _ui.value.copy(toast = text)
    }

    // --- loops ---------------------------------------------------------------------------------

    private fun startLoops(s: FieldSession) {
        loops?.cancel()
        loops = scope.launch {
            launch {
                while (isActive) {
                    try {
                        s.pollEvents(lastEventId).forEach(::onLiveEvent)
                        if (_ui.value.link != Link.ONLINE) _ui.value = _ui.value.copy(link = Link.ONLINE)
                    } catch (e: IOException) {
                        _ui.value = _ui.value.copy(link = Link.OFFLINE)
                    } catch (e: Exception) {
                        log("events: ${describe(e)}")
                    }
                    delay(2_000)
                }
            }
            launch {
                // Safety heartbeat while a tower visit is open (contract §6, lone-worker timer).
                while (isActive) {
                    delay(HEARTBEAT_MS)
                    val v = _ui.value.visitId ?: continue
                    val r = s.send(JobRequests.safetyCheckIn(UUIDv7.generate(), v))
                    log("safety check-in: ${r::class.simpleName}")
                }
            }
        }
    }

    private fun onLiveEvent(ev: JsonObject) {
        lastEventId = ev.s("id") ?: lastEventId
        val kind = ev.s("kind") ?: ev.s("tick_type") ?: return
        val payloadObj = (ev["payload"] as? JsonObject) ?: ev
        val payload = payloadObj.mapValues { (_, v) -> (v as? JsonPrimitive)?.contentOrNull }
        log("event $kind ${payload["doc_number"] ?: payload["title"] ?: ""}")
        val r = runner
        val refresh = r?.onLiveEvent(kind, payload) ?: (kind == "task.assigned")
        when {
            kind == "task.assigned" -> toast("New job: ${payload["title"] ?: payload["type"] ?: "check Today"}")
            r == null && kind == "erp.posted" -> toast("SAP posted document ${payload["doc_number"]?.let(JobRunner::spokenDoc) ?: ""}.")
            r == null && kind == "erp.failed" -> toast("SAP did not accept a posting. Your supervisor can retry it.")
        }
        if (refresh || r == null) refreshTasks()
    }

    private fun nextClimbSeq(): Long {
        val n = prefs.getLong(KEY_CLIMB_SEQ, 0L) + 1
        prefs.edit().putLong(KEY_CLIMB_SEQ, n).apply()
        return n
    }

    // --- helpers -------------------------------------------------------------------------------

    private fun describe(e: Throwable): String = when (e) {
        is HttpError -> when (e.status) {
            401 -> "The pairing code expired or the PC restarted. Make a new code on the PC and scan it."
            403 -> "This phone is not allowed (${e.code ?: "403"}). Make a new code on the PC and scan it."
            else -> e.title?.takeIf { it != "HTTP Error" } ?: "The server said ${e.message}"
        }
        is java.net.ConnectException, is java.net.SocketTimeoutException, is java.net.UnknownHostException ->
            "Cannot reach the PC. Is the phone on the same Wi-Fi, and is START FIELD TEST running?"
        else -> e.message ?: e.javaClass.simpleName
    }

    private fun log(line: String) {
        _ui.value = _ui.value.copy(log = (_ui.value.log + line).takeLast(200))
    }

    fun shutdown() {
        stopWork()
        loops?.cancel()
        location.stop()
        glasses.disconnect()
        phoneSpeech.destroy()
        continuous.stop()
        tts.shutdown()
    }

    private fun JsonObject.s(k: String): String? = (this[k] as? JsonPrimitive)?.contentOrNull

    companion object {
        private const val KEY_PAIRING = "pairing"
        private const val KEY_SCANNER = "scanner"
        private const val KEY_AUDIO_ONLY = "audio_only"
        private const val KEY_GLASSES_SPEECH = "glasses_speech"
        private const val KEY_VISIT = "visit_id"
        private const val KEY_VISIT_SITE = "visit_site_id"
        private const val KEY_CLIMB_SEQ = "climb_seq"
        private const val HEARTBEAT_MS = 5 * 60_000L
    }
}
