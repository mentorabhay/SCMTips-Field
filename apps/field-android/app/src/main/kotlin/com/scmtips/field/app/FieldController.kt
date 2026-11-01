package com.scmtips.field.app

import android.app.Activity
import android.content.Context
import android.os.Build
import androidx.security.crypto.EncryptedSharedPreferences
import androidx.security.crypto.MasterKey
import com.scmtips.field.app.assistant.AssistantClient
import com.scmtips.field.app.assistant.AssistantOutcome
import com.scmtips.field.app.assistant.SiteModes
import com.scmtips.field.app.decisions.DecisionText
import com.scmtips.field.app.decisions.DecisionsView
import com.scmtips.field.app.decisions.PhoneCardDisplay
import com.scmtips.field.app.decisions.SpeechWaiter
import com.scmtips.field.app.decisions.StepUpAsk
import com.scmtips.field.app.decisions.TtsSignals
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
import com.scmtips.field.app.home.SandboxOutcome
import com.scmtips.field.app.home.SandboxStart
import com.scmtips.field.app.home.SandboxStarters
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
import com.scmtips.field.app.session.AttentionWord
import com.scmtips.field.app.session.DecisionPort
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
import com.scmtips.field.app.signin.AccountCredentials
import com.scmtips.field.app.signin.AccountEffect
import com.scmtips.field.app.signin.AccountEvent
import com.scmtips.field.app.signin.AccountFlow
import com.scmtips.field.app.signin.AccountView
import com.scmtips.field.app.signin.SignInLinks
import com.scmtips.field.app.signin.SignInProblem
import com.scmtips.field.app.signin.AccountStore
import com.scmtips.field.app.signin.CoreAccount
import com.scmtips.field.app.signin.FieldAccess
import com.scmtips.field.app.signin.HomeSections
import com.scmtips.field.app.signin.ServerDefaults
import com.scmtips.field.app.signin.SignInDefaults
import com.scmtips.field.app.signin.SiteChoice
import com.scmtips.field.app.signin.SiteRef
import com.scmtips.field.feature.decisions.api.CoreAccountApi
import com.scmtips.field.feature.decisions.api.CoreClient
import com.scmtips.field.feature.decisions.api.CoreSignIn
import com.scmtips.field.feature.decisions.api.OkHttpCoreHttp
import com.scmtips.field.feature.decisions.api.SignInException
import com.scmtips.field.feature.decisions.api.SignInMethod
import com.scmtips.field.feature.decisions.api.StepUpMethod
import com.scmtips.field.feature.decisions.brief.FieldBriefClient
import com.scmtips.field.feature.decisions.flow.ApprovalFlow
import com.scmtips.field.feature.decisions.flow.FlowState
import com.scmtips.field.feature.decisions.flow.LaunchCoordinator
import com.scmtips.field.feature.decisions.flow.Outcome
import com.scmtips.field.feature.decisions.flow.StepUpBroker
import com.scmtips.field.feature.decisions.flow.StepUpEntry
import com.scmtips.field.feature.decisions.flow.UtteranceInbox
import com.scmtips.field.core.common.UUIDv7
import com.scmtips.field.app.home.CaseOutcome
import com.scmtips.field.app.home.CaseStart
import com.scmtips.field.app.home.CaseStarters
import com.scmtips.field.app.look.CameraProbe
import com.scmtips.field.app.look.CameraUsed
import com.scmtips.field.app.look.ClaimReview
import com.scmtips.field.app.look.ClaimsList
import com.scmtips.field.app.look.ClaimsText
import com.scmtips.field.app.look.ClaimsView
import com.scmtips.field.app.look.LookCamera
import com.scmtips.field.app.look.LookCase
import com.scmtips.field.app.look.LookClient
import com.scmtips.field.app.look.LookFlow
import com.scmtips.field.app.look.LookPhotos
import com.scmtips.field.app.look.LookTarget
import com.scmtips.field.app.look.LookView
import com.scmtips.field.app.look.Shot
import com.scmtips.field.app.look.UploadResult
import com.scmtips.field.app.session.LookPort
import com.scmtips.field.app.session.LocalIntents
import com.scmtips.field.app.check.CheckAction
import com.scmtips.field.app.check.CheckClient
import com.scmtips.field.app.check.CheckFlow
import com.scmtips.field.app.check.CheckGrammar
import com.scmtips.field.app.check.CheckView
import com.scmtips.field.app.check.CodeScanner
import com.scmtips.field.app.check.SealCamera
import com.scmtips.field.app.check.SealShot
import com.scmtips.field.app.session.CheckPort
import com.scmtips.field.app.shell.FirstRun
import com.scmtips.field.app.shell.ShellAction
import com.scmtips.field.app.shell.ShellNav
import com.scmtips.field.app.shell.ShellView
import kotlinx.coroutines.CompletableDeferred
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
import kotlinx.coroutines.flow.catch
import kotlinx.coroutines.flow.combine
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
    /** M4 F2: signed in against the SCMTIPS core (null with a QR pairing or signed out). */
    val signedIn: SignedIn? = null,
    val signIn: SignInView = SignInView(),
    /** Which homes Today shows, by the core's capabilities (a QR pairing is field work). */
    val home: HomeSections = HomeSections(decisions = false, fieldWork = true),
    /** M4 F1: decisions waiting, the running review, its card and step-up. */
    val decisions: DecisionsView = DecisionsView(),
    /** The paired site is a sandbox: Today offers a new home receipt and a shelf count. */
    val sandbox: Boolean = false,
    /** The sites field-api lists for a SCMTIPS sign-in (Me → Site), in its order. */
    val sites: List<SiteRef> = emptyList(),
    /** Me → Attention word: only words starting with "Field" are acted on (off by default). */
    val attentionWord: Boolean = false,
    /** M5: the current look (photo, outlines, proposal), its claim and the evidence page. */
    val look: LookView = LookView(),
    /** M5: supervisors' draft claims (Today card) and the running claims review. */
    val claims: ClaimsView = ClaimsView(),
    /** M5: Me → Test glasses camera (Gate 0 probe G0-5). */
    val probe: CameraProbe? = null,
    /** M5-T05: the C3 box check (photo, seal code, verdict, signals, its claim and evidence page). */
    val check: CheckView = CheckView(),
    /** M5-U01: the redesign's shell (first run, tab, page, chosen home, classic layout, reduce motion). */
    val shell: ShellView = ShellView(),
    /** M5-U06: the task id of the open [job] (its done screen's "Next up" leaves it out); null when no job is open. */
    val jobTaskId: String? = null,
    /** M5-L: the in-app sign-in, invite and reset flow (signin/AccountFlow.kt). */
    val account: AccountView = AccountView(),
)

/** Who is signed in against the core (no tokens here: AppUi is drawn and logged freely). */
data class SignedIn(val name: String, val email: String?, val coreBaseUrl: String, val approver: Boolean, val fieldOperator: Boolean)

/** The sign-in form's addresses and state. */
data class SignInView(
    val coreUrl: String = BuildConfig.DEFAULT_CORE_URL,
    val fieldUrl: String = BuildConfig.DEFAULT_FIELD_URL,
    val email: String = "",
    val busy: Boolean = false,
    val error: String? = null,
    /** M5-L: the kind of [error] (wrong details, locked, no Field role, single sign-on, demo off, offline). */
    val problem: SignInProblem? = null,
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

    /** M5: MainActivity opens the phone's camera app for a look photo (the glasses gave none) when this fires. */
    private val _photoRequests = MutableSharedFlow<Unit>(extraBufferCapacity = 1)
    val photoRequests: SharedFlow<Unit> = _photoRequests.asSharedFlow()
    private var phoneShot: CompletableDeferred<android.graphics.Bitmap?>? = null

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
    private val accounts by lazy {
        AccountStore(object : PhoneBinding.Store {
            override fun get(key: String): String? = prefs.getString(key, null)
            override fun put(key: String, value: String) = prefs.edit().putString(key, value).apply()
            override fun remove(key: String) = prefs.edit().remove(key).apply()
        })
    }
    private val workSession = WorkSession { v -> _ui.value = _ui.value.copy(work = v) }
    private val ttsSignals = TtsSignals()
    private val tts = TtsSpeaker(context, { said -> log("🔊 $said") }, { on ->
        ttsSignals.onSpeaking(on)
        scope.launch { workSession.speaking(on); applyHold() }
    })
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
        decisions = object : DecisionPort {
            override val approver: Boolean get() = account?.approver == true
            override val reviewing: Boolean get() = reviewJob?.isActive == true
            override fun startReview() = this@FieldController.startReview()
            override fun heard(text: String, confidence: Float) { reviewInbox.offer(text, confidence) }
        },
        looks = object : LookPort {
            override val reviewingClaims: Boolean get() = claimJob?.isActive == true
            // "I agree" answers whichever photo waits for the site's consent: a look's or a box check's (M5-T05).
            override val consentPending: Boolean get() = lookFlow.consentPending || checkFlow.consentPending
            override fun heardForClaims(text: String, confidence: Float) { claimInbox.offer(text, confidence) }
            // The look runs on its own (camera, upload, models: seconds; the phone camera app: up to 2 min), so
            // the session keeps hearing words such as "stop work" meanwhile.
            override suspend fun look() { scope.launch { lookNow() } }
            override suspend fun claim() = lookFlow.claim()
            override fun startClaims() = startClaimReview()
            override suspend fun startCase(case: LookCase) { CaseStart.of(case)?.let { startCaseNow(it) } }
            override suspend fun agree() { scope.launch { agreeNow() } }
        },
        checks = object : CheckPort {
            override val open: Boolean get() = checkFlow.view.value.open
            override suspend fun act(a: CheckAction) = checkAction(a)
        },
    )

    // --- M5 look and act (docs/design/M5_CONTRACT.md §4) ----------------------------------------
    /** field-api of the moment (a QR pairing or a core sign-in), for the M5 calls. */
    private val liveTransport = object : com.scmtips.field.app.jobs.JobTransport, com.scmtips.field.app.look.BytesPort {
        override suspend fun send(request: com.scmtips.field.app.jobs.ApiRequest) =
            session?.send(request) ?: com.scmtips.field.app.jobs.ApiResult.Offline("not connected")
        override suspend fun put(path: String, bytes: ByteArray, contentType: String) =
            session?.put(path, bytes, contentType) ?: com.scmtips.field.app.jobs.ApiResult.Offline("not connected")
    }
    private val lookClient = LookClient(liveTransport, liveTransport, { _ui.value.deviceId })
    private val lookFlow = LookFlow(
        camera = LookCamera { takeLookPhoto() },
        client = lookClient,
        speaker = speaker,
        onLook = { fill -> runner?.applyLook(fill) },
        baseUrl = { session?.apiBaseUrl },
        log = ::log,
        scope = scope,
    )
    // --- M5-T05: the C3 box check ("Is this unit really new?", docs/design/M5_C3_CONTRACT.md §7) ----------
    private val checkClient = CheckClient(liveTransport, liveTransport, { _ui.value.deviceId })
    private val checkFlow = CheckFlow(
        camera = SealCamera { takeSealPhoto() },
        scanner = CodeScanner { scanSealWithPhone() },
        client = checkClient,
        speaker = speaker,
        baseUrl = { session?.apiBaseUrl },
        log = ::log,
        scope = scope,
    )

    /** A direct phone scan of a seal QR waits here; [onCode] hands the scanned code to it instead of a job. */
    private var sealScan: CompletableDeferred<String?>? = null

    private val caseByTask = mutableMapOf<String, LookCase>()
    private val claimInbox = UtteranceInbox { if (workSession.view.active) REVIEW_LISTEN_SESSION_MS else REVIEW_LISTEN_PHONE_MS }
    private val claimCard = PhoneCardDisplay { !_ui.value.audioOnly }
    private var claimJob: Job? = null

    /** False once the server refused this person's claim decision (403): the Today card is hidden. */
    private var claimsDecider = true

    // --- M4 decisions (F1) --------------------------------------------------------------------
    private var account: CoreAccount? = null
    private val coreHttp = OkHttpCoreHttp()
    private val coreCredentials = AccountCredentials({ account })
    private val reviewInbox = UtteranceInbox { if (workSession.view.active) REVIEW_LISTEN_SESSION_MS else REVIEW_LISTEN_PHONE_MS }
    private val reviewCard = PhoneCardDisplay { !_ui.value.audioOnly }
    private val stepUpBroker = StepUpBroker { toast("Enter your verification code on this phone.") }
    private var reviewJob: Job? = null
    private var launchJob: Job? = null

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
        scope.launch { lookFlow.view.collect { v -> _ui.value = _ui.value.copy(look = v) } }
        scope.launch { checkFlow.view.collect { v -> _ui.value = _ui.value.copy(check = v) } }
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
            attentionWord = prefs.getBoolean(KEY_ATTENTION, false),
        )
        val pairedApi = prefs.getString(KEY_PAIRING, null)?.let { runCatching { PairingPayload.parse(it).apiBaseUrl }.getOrNull() }
        val servers = ServerDefaults(BuildConfig.DEFAULT_CORE_URL, BuildConfig.DEFAULT_FIELD_URL) // per build type (M5-H02)
        val fieldUrl = SignInDefaults.fieldUrl(accounts.lastFieldUrl, pairedApi, servers)
        _ui.value = _ui.value.copy(signIn = SignInView(
            coreUrl = SignInDefaults.coreUrl(accounts.lastCoreUrl, fieldUrl, servers), fieldUrl = fieldUrl, email = accounts.lastEmail.orEmpty(),
        ), account = AccountView(email = accounts.lastEmail.orEmpty()))
        val saved = accounts.load()
        restoreShell(connectedAtStart = saved != null || prefs.getString(KEY_PAIRING, null) != null)
        when {
            saved != null && !saved.accessExpired(System.currentTimeMillis()) -> attachAccount(saved, fromScan = false)
            saved != null -> _ui.value = _ui.value.copy(signIn = _ui.value.signIn.copy(error = "Your SCMTIPS sign-in has expired. Sign in again."))
            else -> prefs.getString(KEY_PAIRING, null)?.let { qr ->
                runCatching { PairingPayload.parse(qr) }.onSuccess { p -> attach(p, fromScan = false) }
            }
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
        if (account != null) { accounts.clear(); account = null; stopLaunches() }
        _ui.value = _ui.value.copy(signedIn = null, home = HomeSections.of(null, paired = true))
        attach(p, fromScan = true)
    }

    /** Connect screen "Try again": the saved code, registered again. */
    fun retryConnect() {
        account?.let { return attachAccount(it, fromScan = true) }
        val p = _ui.value.pairing ?: return
        attach(p, fromScan = true)
    }

    fun unpair() {
        stopWork()
        stopReview(silent = true)
        stopClaimReview(silent = true)
        lookFlow.clear()
        checkFlow.reset()
        claimsDecider = true
        account?.let { a -> signOutOfCore(a) }
        loops?.cancel()
        closeJob(null)
        glasses.disconnect()
        // The device id stays: re-pairing to another site of the same PC reuses it (PhoneBinding scope).
        prefs.edit().remove(KEY_PAIRING).remove(KEY_VISIT).remove(KEY_VISIT_SITE).apply()
        session = null
        _ui.value = AppUi(
            scanner = _ui.value.scanner, audioOnly = _ui.value.audioOnly, glassesSpeech = _ui.value.glassesSpeech,
            glasses = _ui.value.glasses, glassesAdvice = _ui.value.glassesAdvice, log = _ui.value.log,
            attentionWord = _ui.value.attentionWord,
            signIn = _ui.value.signIn.copy(busy = false, error = null, problem = null, coreUrl = accounts.lastCoreUrl ?: _ui.value.signIn.coreUrl,
                fieldUrl = accounts.lastFieldUrl ?: _ui.value.signIn.fieldUrl),
            account = AccountView(email = accounts.lastEmail ?: _ui.value.account.email, demoOff = _ui.value.account.demoOff),
            shell = ShellNav.signedOut(_ui.value.shell).also { saveShell(it) },
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
        val api = phoneApi(s)
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

    private fun phoneApi(s: FieldSession) = object : PhoneBinding.Api {
        override suspend fun exchange(deviceId: String?) = s.bind(deviceId)
        override suspend fun register(serial: String, idempotencyKey: String) = s.registerPhone(
            serial = serial,
            model = "${Build.MANUFACTURER} ${Build.MODEL}",
            osVersion = "Android ${Build.VERSION.RELEASE}",
            appVersion = BuildConfig.VERSION_NAME,
            idempotencyKey = idempotencyKey,
        )
    }

    // --- sign in against the core (M4 F2) -------------------------------------------------------

    /**
     * Sign-in screen: e-mail + password (demo) or a pairing code, at the typed core address. The wearable
     * token is bound to this install's id; the model is Ray-Ban Meta Gen 2 when glasses are registered.
     */
    fun signIn(method: SignInMethod, coreUrl: String, fieldUrl: String) {
        val (core, coreWhy) = SignInDefaults.check(coreUrl, "SCMTIPS")
        val (field, fieldWhy) = SignInDefaults.check(fieldUrl, "SCMTips Field server")
        if (core == null || field == null) {
            _ui.value = _ui.value.copy(signIn = _ui.value.signIn.copy(error = coreWhy ?: fieldWhy, coreUrl = coreUrl, fieldUrl = fieldUrl))
            return
        }
        accounts.rememberServers(core, field)
        val email = ((method as? SignInMethod.Password)?.email ?: (method as? SignInMethod.EmailCode)?.email)?.trim()
        _ui.value = _ui.value.copy(signIn = _ui.value.signIn.copy(busy = true, error = null, problem = null, coreUrl = core, fieldUrl = field,
            email = email ?: _ui.value.signIn.email))
        scope.launch {
            try {
                val model = SignInDefaults.deviceModel(glassesRegistered())
                val a = try {
                    CoreAccount.from(CoreSignIn(core, coreHttp).signIn(method, binding.installId(), model), core, field, System.currentTimeMillis())
                } catch (e: SignInException) {
                    // A core without the app sign-in route: its wearable app's own pairing (decisions only).
                    if (method !is SignInMethod.PairingCode || e.status !in NO_APP_SIGN_IN) throw e
                    val (w, name) = CoreSignIn.pairWearable(core, coreHttp, method.code, binding.installId(), model)
                    CoreAccount.paired(w, name, core, field)
                }
                accounts.save(a)
                prefs.edit().remove(KEY_PAIRING).apply() // one link to field-api at a time: the sign-in replaces a QR pairing
                log("Signed in to SCMTIPS as ${a.displayName} (${model.wire}); approve decisions: ${a.approver}, field work: ${a.fieldOperator}")
                _ui.value = _ui.value.copy(signIn = _ui.value.signIn.copy(busy = false, error = null, problem = null),
                    account = AccountView(demoOff = _ui.value.account.demoOff, email = email ?: _ui.value.account.email))
                attachAccount(a, fromScan = true)
            } catch (e: SignInException) {
                _ui.value = _ui.value.copy(signIn = _ui.value.signIn.copy(busy = false, error = e.message, problem = SignInProblem.of(e.status, e.code)))
                val demoOff = e.status == 403 && e.code == "demo_off"
                if (demoOff || method is SignInMethod.EmailCode) onAccount(AccountEvent.SignInFailed(core, demoOff, method))
            } catch (e: kotlinx.coroutines.CancellationException) {
                throw e
            } catch (e: Exception) {
                _ui.value = _ui.value.copy(signIn = _ui.value.signIn.copy(busy = false, error = describe(e)))
            }
        }
    }

    /** Uses a signed-in account: field-api through the core token (as a QR pairing), decisions through the wearable token. */
    private fun attachAccount(a: CoreAccount, fromScan: Boolean) {
        account = a
        val person = Person.fromName(a.displayName) ?: Person.UNKNOWN
        _ui.value = _ui.value.copy(signedIn = signedIn(a), person = person, home = HomeSections.of(a, paired = false), deviceId = null,
            connecting = a.fieldOperator && a.hasFieldAccess, connectError = null)
        if (a.approver) { refreshDecisions(); startLaunches() }
        if (!a.hasFieldAccess) return // the core app's pairing: decisions only (the spoken brief then falls back to the template)
        // A core-signed-in phone is not registered with POST /v1/devices (409): the exchange itself registers or
        // links the field device (serial_no = the core device id) and answers its id (stream C, M4-C01).
        val s = FieldSession(a.fieldBaseUrl, a.accessToken, null)
        session = s
        assistant = AssistantClient(s) { UUIDv7.generate() }
        siteModes = SiteModes(s)
        scope.launch {
            try {
                s.bind(null)
                val id = s.exchangedDeviceId ?: throw HttpError(0, null, null, null, "field-api did not say which device this phone is")
                s.deviceId = id // later exchanges name it; field-api checks it against the core device id
                val granted = a.withPermissions(s.corePermissions)
                if (granted !== a && account === a) {
                    account = granted
                    accounts.save(granted)
                    _ui.value = _ui.value.copy(signedIn = signedIn(granted), home = HomeSections.of(granted, paired = false))
                    if (granted.approver && !a.approver) { refreshDecisions(); startLaunches() }
                }
                _ui.value = _ui.value.copy(deviceId = id, connecting = false, link = Link.ONLINE)
                val sites = (s.send(SiteModes.sites()) as? com.scmtips.field.app.jobs.ApiResult.Ok)?.body ?: JsonObject(emptyMap())
                val listed = SiteChoice.all(sites)
                val site = SiteChoice.pick(a.sites, listed, accounts.chosenSite)
                _ui.value = _ui.value.copy(sites = listed)
                if (site == null) {
                    log("Signed in; field-api lists no site for ${a.displayName}")
                    _ui.value = _ui.value.copy(pairing = null)
                } else {
                    siteModes?.remember(site.id, site.mode)
                    _ui.value = _ui.value.copy(pairing = a.pairing(site.id, site.name), sandbox = site.mode == SiteModes.SANDBOX)
                    log("Connected to ${site.name}; phone device $id")
                }
                startLoops(s)
                refreshTasks()
            } catch (e: Exception) {
                if (binding.renewAfterRevoke(e)) {
                    // Removed in the console (M5-H06): sign out here; the next sign-in uses a new install id.
                    log("⚠ field-api: this phone was removed in the console; sign in again to add it as a new device")
                    signOutOfCore(a)
                    _ui.value = _ui.value.copy(signedIn = null, pairing = null, connecting = false, connectError = null,
                        home = HomeSections.of(null, paired = false), signIn = _ui.value.signIn.copy(busy = false, error = REVOKED_SIGN_IN_AGAIN))
                    return@launch
                }
                val why = describe(e)
                log("⚠ field-api: $why")
                _ui.value = _ui.value.copy(connecting = false, connectError = why, link = if (e is IOException) Link.OFFLINE else _ui.value.link)
                // No Field role for this core account (403 NO-FIELD-ROLE): field-api's sentence on the sign-in screen too.
                (e as? HttpError)?.let(FieldAccess::noFieldRole)?.let { why ->
                    _ui.value = _ui.value.copy(signIn = _ui.value.signIn.copy(error = why, problem = SignInProblem.NO_FIELD_ROLE))
                    // M5-L: an account that can do nothing in the app (no Field role, no approvals) goes back to the sign-in
                    // screen, where the sentence and "Try the SAMPLE demo" are shown; an approver keeps its approvals.
                    if (!a.approver && account === a) {
                        signOutOfCore(a)
                        _ui.value = _ui.value.copy(signedIn = null, pairing = null, connectError = null, home = HomeSections.of(null, paired = false))
                    }
                }
            }
        }
    }

    private fun signedIn(a: CoreAccount) = SignedIn(a.displayName, a.email, a.coreBaseUrl, a.approver, a.fieldOperator && a.hasFieldAccess)

    /** Me → Sign out: the core forgets this device session (best effort), the phone forgets every token. */
    private fun signOutOfCore(a: CoreAccount) {
        val api = CoreClient(a.coreBaseUrl, coreCredentials, coreHttp)
        val sid = a.wearable.sessionId
        if (a.wearable.present) scope.launch { runCatching { api.revoke(sid) }.onFailure { log("sign-out: the core was not told (${it.javaClass.simpleName})") } }
        stopLaunches()
        accounts.clear()
        account = null
    }

    // --- in-app accounts (M5-L: e-mail code, invite, reset, App Links) ------------------------------

    /** Every tap of the sign-in, invite and reset screens, and the answers of their calls (rules: signin/AccountFlow.kt). */
    fun onAccount(e: AccountEvent) {
        val user = e is AccountEvent.Open || e is AccountEvent.Back || e is AccountEvent.Forgot || e is AccountEvent.Pasted ||
            e is AccountEvent.Scanned || e is AccountEvent.Link || e is AccountEvent.UsePassword || e is AccountEvent.SendCode
        if (user && _ui.value.signIn.error != null && !_ui.value.signIn.busy) {
            _ui.value = _ui.value.copy(signIn = _ui.value.signIn.copy(error = null, problem = null))
        }
        val step = AccountFlow.reduce(_ui.value.account, e)
        _ui.value = _ui.value.copy(account = step.view)
        step.effects.forEach(::runAccountEffect)
    }

    /**
     * MainActivity: an App Link (https://app.scmtips.com/reset/confirm, /invite/…, /pair) opened the app. Other
     * links are left alone (the Meta AI callback and the glasses' voice launch have their own handling).
     */
    fun openLink(uri: String?) {
        val link = SignInLinks.parse(uri, setOf(SignInLinks.WEB_HOST)) ?: return
        val signedIn = _ui.value.signedIn != null || _ui.value.pairing != null
        log("App Link: ${link.javaClass.simpleName}")
        if (signedIn) return toast(com.scmtips.field.app.signin.AccountText.SIGNED_IN_ALREADY)
        onAccount(AccountEvent.Link(link, signedIn = false))
    }

    /** "Scan a code from your computer": the scanner's text (a console App Link, a bare code or the PC pairing QR). */
    fun scannedSignInCode(text: String) = onAccount(AccountEvent.Scanned(text))

    private fun runAccountEffect(effect: AccountEffect) {
        when (effect) {
            is AccountEffect.SignIn -> signIn(effect.method, _ui.value.signIn.coreUrl, _ui.value.signIn.fieldUrl)
            is AccountEffect.Show -> shell(ShellAction.Go(effect.step))
            is AccountEffect.PcPairing -> pair(effect.text)
            is AccountEffect.RequestCode -> withCore { api -> onAccount(AccountEvent.CodeSent(api.requestCode(effect.email, binding.installId()), System.currentTimeMillis())) }
            is AccountEffect.LoadInvite -> withCore { api -> onAccount(AccountEvent.InviteRead(effect.token, api.invite(effect.token))) }
            is AccountEffect.AcceptInvite -> withCore { api ->
                onAccount(AccountEvent.InviteAccepted(api.acceptInvite(effect.token, effect.acceptance), effect.email, effect.acceptance.password))
            }
            is AccountEffect.RequestReset -> withCore { api -> onAccount(AccountEvent.ResetSent(api.requestReset(effect.email))) }
            is AccountEffect.ConfirmReset -> withCore { api -> onAccount(AccountEvent.ResetDone(api.confirmReset(effect.token, effect.password))) }
        }
    }

    /** One public account call to the SCMTIPS address the sign-in screen is set to (checked as on sign-in). */
    private fun withCore(call: suspend (CoreAccountApi) -> Unit) {
        val (core, why) = SignInDefaults.check(_ui.value.signIn.coreUrl, "SCMTIPS")
        if (core == null) {
            _ui.value = _ui.value.copy(account = _ui.value.account.copy(busy = false, error = why))
            return
        }
        scope.launch {
            try {
                call(CoreAccountApi(core, coreHttp))
            } catch (e: kotlinx.coroutines.CancellationException) {
                throw e
            } catch (e: Exception) {
                _ui.value = _ui.value.copy(account = _ui.value.account.copy(busy = false, error = describe(e)))
            }
        }
    }

    // --- decisions (M4 F1) ------------------------------------------------------------------------

    /** How many decisions wait for this approver (GET /v1/wearable/next); null when it could not be asked. */
    private suspend fun waitingDecisions(): Int? = nextDecision()?.first

    /** The same one call, also keeping the item it answered (M5-U06: the Approvals home draws its title and options). */
    private suspend fun nextDecision(): Pair<Int, com.scmtips.field.feature.decisions.api.NextItem?>? {
        val a = account?.takeIf { it.approver } ?: return null
        return try {
            val item = CoreClient(a.coreBaseUrl, coreCredentials, coreHttp).next()
            (if (item == null) 0 else maxOf(item.waiting, 1)) to item
        } catch (e: kotlinx.coroutines.CancellationException) {
            throw e
        } catch (e: Exception) {
            log("decisions: ${e.message ?: e.javaClass.simpleName}")
            null
        }
    }

    fun refreshDecisions() {
        scope.launch {
            nextDecision()?.let { (n, item) -> _ui.value = _ui.value.copy(decisions = _ui.value.decisions.copy(waiting = n, next = item)) }
        }
    }

    /** Decisions card "Review now", the session's "decisions", or a launch from the glasses. */
    fun startReview() {
        val a = account ?: return toast("Sign in to SCMTIPS first.")
        if (!a.approver) return toast("Your SCMTIPS role does not approve decisions.")
        if (reviewJob?.isActive == true) return
        val flow = ApprovalFlow(
            api = CoreClient(a.coreBaseUrl, coreCredentials, coreHttp),
            briefs = FieldBriefClient({ account?.fieldBaseUrl }, { coreCredentials.token }, { coreCredentials.deviceId }, { session?.bearer() }, coreHttp, log = ::log),
            display = reviewCard,
            voice = SpeechWaiter(speaker, ttsSignals),
            ear = reviewInbox,
            stepUp = stepUpBroker,
            onUnauthorized = {
                accounts.clear()
                account = null
                _ui.value = _ui.value.copy(signIn = _ui.value.signIn.copy(error = "Your SCMTIPS sign-in has ended. Sign in again."))
            },
        )
        reviewJob = scope.launch {
            _ui.value = _ui.value.copy(decisions = _ui.value.decisions.copy(reviewing = true, last = null))
            val mirror = launch {
                combine(flow.state, reviewCard.card, reviewInbox.waiting, stepUpBroker.pending) { st, card, listening, pending ->
                    _ui.value.decisions.copy(
                        state = DecisionText.state(st), card = card, listening = listening,
                        briefSource = (st as? FlowState.Presenting)?.briefSource ?: _ui.value.decisions.briefSource,
                        stepUp = pending?.let { StepUpAsk(it.retryMessage) },
                    )
                }.collect { v -> _ui.value = _ui.value.copy(decisions = v.copy(reviewing = true)) }
            }
            try {
                val end = try {
                    flow.run()
                } catch (e: kotlinx.coroutines.CancellationException) {
                    throw e
                } catch (e: Exception) { // never crash the app over a review
                    log("⚠ decision review: ${e.message ?: e.javaClass.simpleName}")
                    FlowState.Failed(e.message ?: e.javaClass.simpleName)
                }
                log("decision review: ${DecisionText.state(end)}")
                _ui.value = _ui.value.copy(decisions = _ui.value.decisions.copy(last = DecisionText.state(end)))
                if (end is FlowState.NeedsSignIn) scope.launch { unpair() } // after this review has ended
                if (end is FlowState.Finished && end.outcome == Outcome.EXECUTED && workSession.view.active) {
                    waitingDecisions()?.let { n -> conductor.decisionsWaiting(n) }
                }
            } finally {
                mirror.cancel()
                _ui.value = _ui.value.copy(decisions = _ui.value.decisions.copy(reviewing = false, card = null, listening = false, stepUp = null))
                refreshDecisions()
            }
        }
    }

    /** The review screen's Stop: nothing is sent after it; a read-back that was not confirmed changes nothing. */
    fun stopReview(silent: Boolean = false) {
        val j = reviewJob ?: return
        if (!j.isActive) return
        stepUpBroker.pending.value?.let { stepUpBroker.answer(it, null) }
        j.cancel()
        if (!silent) speaker.say("Stopped. Nothing more was sent.")
    }

    fun decisionButton(id: String) {
        if (!reviewCard.press(id)) toast("That card is no longer open.")
    }

    /** The step-up dialog's answer: a code (never logged) or null for Cancel. */
    fun answerStepUp(method: StepUpMethod, code: String?) {
        val p = stepUpBroker.pending.value ?: return
        stepUpBroker.answer(p, code?.trim()?.takeIf { it.isNotEmpty() }?.let { StepUpEntry(method, it) })
    }

    /** Meta AI launched the app from the glasses ("Hey Meta, start SCMTips Field"). */
    fun onVoiceLaunch() {
        if (account?.approver == true) startReview()
    }

    private fun startLaunches() {
        if (launchJob?.isActive == true || !glassesRegistered()) return
        launchJob = LaunchCoordinator(
            // A toolkit that refuses the voice-invocation stream ends it here, never in the app's scope.
            launches = glasses.launches.catch { e -> log("glasses launches: ${e.message ?: e.javaClass.simpleName}") },
            scope = scope,
            canReview = { account?.approver == true },
            startReview = ::startReview,
        ).start()
    }

    /** The toolkit may have failed to start (FieldApplication.datInitError): then there are no glasses. */
    private fun glassesRegistered(): Boolean = toolkitError() == null && runCatching { glasses.isRegistered }.getOrDefault(false)

    private fun stopLaunches() {
        launchJob?.cancel()
        launchJob = null
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
            siteModes?.let { m -> m.prime(site); _ui.value = _ui.value.copy(sandbox = m.isSandbox(site)) }
            refreshClaims()
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
        val case = caseByTask[t.id]
        if (t.type == JobType.RECEIVE) lookFlow.forTask(t.id, case ?: LookCase.GENERIC)
        startRunner(JobRunner(
            t, s, speaker, _ui.value.deviceId, visitId = visit, siteId = site,
            siteLabel = siteLabel, scanner = _ui.value.scanner, nextSeq = ::nextClimbSeq, unknownCodes = unknownCodes,
            lookHint = case?.let { CaseStart.of(it)?.introHint },
        ))
    }

    fun openStarter(type: JobType) {
        val id = TodayModel.starters(_ui.value.tasks).firstOrNull { it.type == type }?.taskId
        if (id == null) toast(TodayModel.noneOpen(type)) else openTask(id)
    }

    /** Today on a sandbox site: a new home receipt, or a count of one shelf (field-api's sandbox routes). */
    fun startSandbox(what: SandboxStart, bin: String? = null) {
        val s = session ?: return toast("Connect this phone to the PC first.")
        val site = _ui.value.pairing?.siteId ?: return toast("No site is linked to this phone.")
        scope.launch {
            when (val r = SandboxStarters.start(s, site, what, bin)) {
                is SandboxOutcome.Created -> {
                    log("sandbox ${what.name.lowercase()}: task ${r.taskId}${r.refDocNo?.let { " ($it)" } ?: ""}")
                    refreshTasksNow()
                    if (_ui.value.tasks.any { it.id == r.taskId }) openTask(r.taskId) else toast("${what.label} is ready on Today.")
                }
                is SandboxOutcome.Refused -> toast(r.text)
            }
        }
    }

    fun startPractice() {
        startRunner(JobRunner(Practice.task, PracticeTransport(), speaker, deviceId = "practice", practice = true, scanner = _ui.value.scanner))
    }

    private fun startRunner(r: JobRunner) {
        closeJob(null)
        runner = r
        var toldDone = false
        var askedEvidence = false
        runnerJobs += scope.launch {
            r.view.collect { v ->
                _ui.value = _ui.value.copy(job = v, jobTaskId = r.task.id)
                syncVisit(r)
                if (r.isDone && !toldDone && !r.practice && workSession.view.active) {
                    toldDone = true
                    scope.launch { conductor.stepDone() }
                }
                // M5: a receipt posted from a look gets its evidence page, opened on the phone.
                val doc = r.postedDocument
                if (doc != null && r.usedLook && !askedEvidence) {
                    askedEvidence = true
                    scope.launch { lookFlow.evidence(doc, r.postedYear) }
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
        _ui.value = _ui.value.copy(job = null, jobTaskId = null, toast = note ?: _ui.value.toast)
        // A posted look stays for "make a claim" and its evidence page until the next job opens; its label poll stops.
        lookFlow.leave()
        if (!r.usedLook && _ui.value.look.evidenceUrl == null) lookFlow.clear()
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
        // M5-T05: a direct phone scan of a seal QR asked for by the box check goes to it, not to a job.
        sealScan?.let { waiting -> if (waiting.complete(code)) return }
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
            // Me → Attention word: the open microphone acts only on words that start with "Field" (hold-to-talk is exempt).
            val words = if (source == "phone") text else AttentionWord.filter(text, _ui.value.attentionWord) ?: run {
                log("🎤 [$source] ignored, no attention word: $text")
                return
            }
            log("🎤 [$source ${"%.2f".format(java.util.Locale.ROOT, confidence)}] $words")
            scope.launch { log("→ ${conductor.heard(words, confidence).name.lowercase()}") }
            return
        }
        if (source != "phone") return // no session: only the operator's own hold-to-talk is heard (A-03)
        log("🎤 [$source ${"%.2f".format(java.util.Locale.ROOT, confidence)}] $text")
        if (reviewJob?.isActive == true) { reviewInbox.offer(text, confidence); return }
        if (claimJob?.isActive == true) { claimInbox.offer(text, confidence); return }
        CheckGrammar.action(text, confidence, checkFlow.view.value.open)?.let { a -> scope.launch { checkAction(a) }; return }
        val local = LocalIntents.parse(text)
        if (local == LocalIntents.Intent.Agree && (lookFlow.consentPending || checkFlow.consentPending) && confidence >= JobGrammar.FLOOR) {
            scope.launch { agreeNow() }; return
        }
        if (local == LocalIntents.Intent.Claims) return startClaimReview()
        if (local is LocalIntents.Intent.NewCase) { CaseStart.of(local.case)?.let(::startCase); return }
        when (JobGrammar.parse(text, confidence)) {
            Command.Capture -> requestScan()
            Command.Look -> return lookButton()
            Command.Claim -> return claimButton()
            else -> Unit
        }
        if (runner != null) runnerAct(JobAction.Heard(text, confidence))
    }

    // --- work session (M3 §5) ------------------------------------------------------------------

    /** "Start work" on Today (MainActivity asks for the microphone first), or the glasses connecting. */
    fun startWork() {
        val approver = account?.approver == true
        if ((_ui.value.pairing == null || _ui.value.deviceId == null) && !approver) return toast("Connect this phone to the PC first.")
        if (workSession.start(MicSource.NONE, glasses.status.value.session == "STARTED") == null) return
        WorkSessionService.start(context)
        log("work session started")
        frames.reset()
        applyMic()
        applyStreaming()
        val site = _ui.value.pairing?.siteId
        // The greeting is spoken at once from the phone's own task list; nothing waits on the server first.
        scope.launch { conductor.start() }
        if (site != null) scope.launch { siteModes?.prime(site) }
        if (approver) scope.launch { waitingDecisions()?.let { n -> conductor.decisionsWaiting(n) } }
    }

    fun stopWork() {
        if (workSession.stop() == null) return
        stopReview(silent = true)
        stopClaimReview(silent = true)
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
        // Registered with the Meta AI app while signed in as an approver: answer "Hey Meta, start SCMTips Field".
        if (g.registration == "REGISTERED" && account?.approver == true && launchJob?.isActive != true) startLaunches()
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
        // M5-T05: the box check reads the seal from its own photo; the same QR in the video is not a second scan.
        if (checkFlow.view.value.open) return
        val r = runner
        when {
            r == null -> onCode(codes.first())
            r.isScanStep -> onCode(r.bestOf(codes) ?: codes.first())
            else -> Unit // not a scan step: codes seen in passing are ignored
        }
    }

    // --- M5: look, claims, cases, camera test ---------------------------------------------------

    /** The job screen's Look button (and "look" by hold-to-talk). */
    fun lookButton() {
        scope.launch { lookNow() }
    }

    fun claimButton() {
        scope.launch { lookFlow.claim() }
    }

    fun agreeToPhotos() {
        scope.launch { lookFlow.agree() }
    }

    fun closeEvidence() {
        lookFlow.closeEvidence()
        checkFlow.closeEvidence()
    }

    /** M5-U06: the receipt's done screen, "Evidence page": the look's evidence page again (no new request). */
    fun reopenEvidence() {
        lookFlow.reopenEvidence()
    }

    private suspend fun lookNow() {
        val r = runner
        val site = r?.task?.siteId ?: _ui.value.pairing?.siteId
        if (r == null || r.practice || r.task.type != JobType.RECEIVE || site == null) {
            speaker.say("Open a delivery first. Say new grocery delivery, or start receive.")
            return
        }
        lookFlow.look(LookTarget(r.task.id, r.lookLineId, site, caseByTask[r.task.id] ?: LookCase.GENERIC))
    }

    /**
     * A look photo: the glasses camera through the Meta toolkit when the glasses are connected; else (or when
     * they give none) the phone's camera app, only while the app is on screen. Faces are blurred on the phone.
     */
    private suspend fun takeLookPhoto(): Shot = when (val g = grabPhoto("look", "Take the photo with the phone.")) {
        is Grab.None -> Shot.Failed(g.text)
        is Grab.Got -> prepared(g.bmp, g.camera, g.at, g.ms, g.note)
    }

    /** A camera's full-size photo before blurring (the seal's QR is read from it), or why there is none. */
    private sealed interface Grab {
        class Got(val bmp: android.graphics.Bitmap, val camera: CameraUsed, val at: Long, val ms: Long, val note: String?) : Grab
        class None(val text: String) : Grab
    }

    /** The glasses camera when connected; else (or when they give none) the phone's camera app, only on screen. */
    private suspend fun grabPhoto(what: String, phonePrompt: String): Grab {
        val glassesOn = glasses.status.value.session == "STARTED"
        if (glassesOn) {
            val t0 = System.currentTimeMillis()
            val bmp = glasses.capturePhoto()
            val ms = System.currentTimeMillis() - t0
            if (bmp != null) {
                log("$what photo from the glasses: ${bmp.width}x${bmp.height} in $ms ms")
                return Grab.Got(bmp, CameraUsed.GLASSES, t0, ms, null)
            }
        }
        if (!inForeground) return Grab.None(if (glassesOn) "No photo from the glasses. Open the app on the phone to use its camera." else "Connect the glasses, or open the app on the phone to use its camera.")
        speaker.say(if (glassesOn) "No photo from the glasses. Take it with the phone." else phonePrompt)
        val t0 = System.currentTimeMillis()
        val waiting = CompletableDeferred<android.graphics.Bitmap?>()
        phoneShot = waiting
        _photoRequests.tryEmit(Unit)
        val bmp = kotlinx.coroutines.withTimeoutOrNull(PHONE_PHOTO_MS) { waiting.await() }
        phoneShot = null
        return if (bmp == null) Grab.None("No photo was taken.")
        else Grab.Got(bmp, CameraUsed.PHONE, t0, System.currentTimeMillis() - t0, if (glassesOn) "Used the phone camera." else null)
    }

    // --- M5-T05: the C3 box check ------------------------------------------------------------------

    /** Today's card, its buttons, and the words of CheckGrammar (session or hold-to-talk). Runs on its own. */
    fun checkButton(a: CheckAction) {
        scope.launch { checkAction(a) }
    }

    private suspend fun checkAction(a: CheckAction) {
        when (a) {
            CheckAction.START, CheckAction.AGAIN -> scope.launch { checkNow() } // camera and registry: seconds
            CheckAction.CLAIM -> checkFlow.claim()
            CheckAction.EVIDENCE -> checkFlow.evidence()
            CheckAction.DONE -> checkFlow.done()
            CheckAction.RETRY -> scope.launch { checkFlow.retry() }
            CheckAction.PHONE_SCAN -> scope.launch { checkFlow.scanWithPhone() }
            CheckAction.AGREE -> scope.launch { checkFlow.agree() }
            CheckAction.CODE_ONLY -> scope.launch { checkFlow.codeOnly() }
        }
    }

    /** No task is needed (contract §7); the site is the linked one (the server defaults it when there is none). */
    private suspend fun checkNow() {
        if (session == null) {
            toast("Connect this phone to the PC first.")
            return speaker.say("Connect this phone to Field first.")
        }
        checkFlow.start(_ui.value.pairing?.siteId)
    }

    /** "I agree": the photo that waits for the site's consent (a box check's first, else a look's). */
    private suspend fun agreeNow() = if (checkFlow.consentPending) checkFlow.agree() else lookFlow.agree()

    /** The seal photo: the QR read on the phone from the full-size photo, then the photo blurred for upload. */
    private suspend fun takeSealPhoto(): SealShot = when (val g = grabPhoto("seal", "Take a photo of the seal code with the phone.")) {
        is Grab.None -> SealShot.Failed(g.text)
        is Grab.Got -> {
            val codes = barcodes.read(g.bmp)
            log("seal photo ${g.bmp.width}x${g.bmp.height}: ${if (codes.isEmpty()) "no code" else "${codes.size} code(s)"}")
            val photo = withContext(Dispatchers.Default) { LookPhotos.prepare(g.bmp, g.camera, g.at, g.ms) }
            if (photo == null) log("seal photo: the face check failed, so the photo is not sent (code only)")
            else if (photo.facesBlurred > 0) log("seal photo: ${photo.facesBlurred} face(s) blurred on the phone")
            SealShot.Taken(photo, codes, g.camera, g.note)
        }
    }

    /** The phone's code scanner for the seal QR (MainActivity: Google's scanner UI), only while the app is on screen. */
    private suspend fun scanSealWithPhone(): String? {
        if (!inForeground) {
            speaker.say("Open the app on the phone to scan the code.")
            return null
        }
        val waiting = CompletableDeferred<String?>()
        sealScan = waiting
        _cameraRequests.tryEmit(Unit)
        val code = kotlinx.coroutines.withTimeoutOrNull(PHONE_PHOTO_MS) { waiting.await() }
        sealScan = null
        return code
    }

    /** MainActivity: the phone scanner was closed without a code (a waiting seal scan gets none). */
    fun scanCancelled() {
        sealScan?.complete(null)
    }

    private suspend fun prepared(bmp: android.graphics.Bitmap, camera: CameraUsed, at: Long, ms: Long, note: String?): Shot {
        val photo = withContext(Dispatchers.Default) { LookPhotos.prepare(bmp, camera, at, ms) }
            ?: return Shot.Failed("The photo could not be checked for faces, so it was not sent.")
        if (photo.facesBlurred > 0) log("look photo: ${photo.facesBlurred} face(s) blurred on the phone")
        return Shot.Taken(photo, note)
    }

    /** MainActivity: the camera app's photo file (null when cancelled or unreadable). */
    fun phonePhotoTaken(file: File?) {
        val waiting = phoneShot ?: return
        scope.launch {
            val bmp = file?.let { f -> withContext(Dispatchers.IO) { runCatching { LookPhotos.decodePhoneFile(f) }.getOrNull() } }
            file?.delete()
            waiting.complete(bmp)
        }
    }

    /** Today on a sandbox site: "New grocery delivery" / "New pharmacy delivery" (contract §1). */
    fun startCase(start: CaseStart) {
        scope.launch { startCaseNow(start) }
    }

    private suspend fun startCaseNow(start: CaseStart) {
        val s = session ?: return toast("Connect this phone to the PC first.")
        val site = _ui.value.pairing?.siteId ?: return toast("No site is linked to this phone.")
        when (val r = CaseStarters.start(s, site, start)) {
            is CaseOutcome.Created -> {
                caseByTask[r.taskId] = start.case
                log("case ${start.case.wire}: task ${r.taskId}${r.refDocNo?.let { " ($it)" } ?: ""}")
                refreshTasksNow()
                if (_ui.value.tasks.any { it.id == r.taskId }) openTask(r.taskId) else toast("${start.label} is ready on Today.")
            }
            is CaseOutcome.NotAvailable -> { toast(r.text); if (workSession.view.active) speaker.say(r.text) }
            is CaseOutcome.Refused -> { toast(r.text); if (workSession.view.active) speaker.say(r.text) }
        }
    }

    fun refreshClaims() {
        scope.launch {
            if (session == null) return@launch
            val drafts = when (val r = lookClient.drafts()) {
                // Operators may read claims (field.claim.read) but only supervisors decide (field.claim.decide).
                is ClaimsList.Ok -> r.claims.takeIf { claimsDecider }
                ClaimsList.NotAllowed -> null
                is ClaimsList.Failed -> return@launch log("claims: ${r.text}")
            }
            _ui.value = _ui.value.copy(claims = _ui.value.claims.copy(waiting = drafts?.size, drafts = drafts))
        }
    }

    /** Today's Claims card, or "claims" / "next claim" said: the supervisor's review by voice. */
    fun startClaimReview() {
        if (session == null) return toast("Connect this phone to the PC first.")
        if (claimJob?.isActive == true || reviewJob?.isActive == true) return
        val flow = ClaimReview(lookClient, SpeechWaiter(speaker, ttsSignals), claimInbox, claimCard)
        claimJob = scope.launch {
            _ui.value = _ui.value.copy(claims = _ui.value.claims.copy(reviewing = true, last = null))
            val mirror = launch {
                combine(flow.state, claimCard.card, claimInbox.waiting) { st, card, listening ->
                    _ui.value.claims.copy(state = ClaimsText.state(st), card = card, listening = listening)
                }.collect { v -> _ui.value = _ui.value.copy(claims = v.copy(reviewing = true)) }
            }
            try {
                val end = try {
                    flow.run()
                } catch (e: kotlinx.coroutines.CancellationException) {
                    throw e
                } catch (e: Exception) {
                    log("⚠ claims review: ${e.message ?: e.javaClass.simpleName}")
                    com.scmtips.field.app.look.ClaimFlowState.Failed(e.message ?: e.javaClass.simpleName)
                }
                log("claims review: ${ClaimsText.state(end)}")
                if ((end as? com.scmtips.field.app.look.ClaimFlowState.Finished)?.outcome == com.scmtips.field.app.look.ClaimOutcome.NOT_ALLOWED) claimsDecider = false
                _ui.value = _ui.value.copy(claims = _ui.value.claims.copy(last = ClaimsText.state(end)))
            } finally {
                mirror.cancel()
                _ui.value = _ui.value.copy(claims = _ui.value.claims.copy(reviewing = false, card = null, listening = false))
                refreshClaims()
            }
        }
    }

    fun stopClaimReview(silent: Boolean = false) {
        val j = claimJob ?: return
        if (!j.isActive) return
        j.cancel()
        if (!silent) speaker.say("Stopped. Nothing more was changed.")
    }

    fun claimCardButton(id: String) {
        if (!claimCard.press(id)) toast("That card is no longer open.")
    }

    /** Me → Test glasses camera (G0-5): one toolkit photo; its size and delay; nothing is sent. */
    fun testGlassesCamera() {
        if (_ui.value.probe?.busy == true) return
        if (glasses.status.value.session != "STARTED") {
            _ui.value = _ui.value.copy(probe = CameraProbe(message = "Connect the glasses first (Me → Smart glasses → Connect)."))
            return
        }
        _ui.value = _ui.value.copy(probe = CameraProbe(busy = true, message = "Taking one photo with the glasses…"))
        scope.launch {
            val t0 = System.currentTimeMillis()
            val bmp = glasses.capturePhoto()
            val ms = System.currentTimeMillis() - t0
            if (bmp == null) {
                val why = glasses.status.value.lastError ?: "the toolkit gave no photo"
                log("G0-5 glasses camera: no photo ($why) after $ms ms")
                _ui.value = _ui.value.copy(probe = CameraProbe(delayMs = ms, message = "No photo: $why"))
                return@launch
            }
            log("G0-5 glasses camera: ${bmp.width}x${bmp.height} in $ms ms")
            val preview = withContext(Dispatchers.Default) { LookPhotos.prepare(bmp, CameraUsed.GLASSES, t0, ms) }
            _ui.value = _ui.value.copy(probe = CameraProbe(width = bmp.width, height = bmp.height, delayMs = ms, preview = preview,
                message = if (preview == null) "Face check failed: this photo cannot be uploaded." else "Nothing was sent. Tap Upload to send this photo to the Field server."))
        }
    }

    /** The camera test's Upload: the blurred photo through the captures API (no job). */
    fun uploadProbe(agree: Boolean = false) {
        val p = _ui.value.probe ?: return
        val photo = p.preview ?: return
        val site = _ui.value.pairing?.siteId ?: return toast("No site is linked to this phone.")
        _ui.value = _ui.value.copy(probe = p.copy(busy = true, message = "Uploading…", needsConsent = false))
        scope.launch {
            if (agree && !lookClient.consent(site)) {
                _ui.value = _ui.value.copy(probe = p.copy(busy = false, message = "The consent was not recorded."))
                return@launch
            }
            val next = when (val r = lookClient.upload(photo, null, site, "camera_test")) {
                is UploadResult.Uploaded -> p.copy(busy = false, uploadedCaptureId = r.captureId, message = "Uploaded as capture ${r.captureId}.")
                UploadResult.NeedsConsent -> p.copy(busy = false, needsConsent = true, message = com.scmtips.field.app.look.LookFlow.CONSENT_TEXT)
                is UploadResult.Failed -> p.copy(busy = false, message = r.text)
            }
            _ui.value = _ui.value.copy(probe = next)
        }
    }

    fun closeProbe() {
        _ui.value = _ui.value.copy(probe = null)
    }

    // --- Me ------------------------------------------------------------------------------------

    /** Me → Site → Change (signed in with SCMTIPS): the next site field-api lists; Today reloads for it (M5-H05). */
    fun nextSite() {
        val current = _ui.value.pairing?.siteId
        val site = SiteChoice.next(_ui.value.sites, current) ?: return
        chooseSite(site.id)
    }

    /** M5-U: the site picked on first run's Site and role, or Profile's site list (signed in with SCMTIPS). */
    fun chooseSite(siteId: String) {
        val a = account ?: return
        val site = _ui.value.sites.firstOrNull { it.id == siteId } ?: return
        if (site.id == _ui.value.pairing?.siteId) return
        accounts.chosenSite = site.id
        siteModes?.remember(site.id, site.mode)
        _ui.value = _ui.value.copy(pairing = a.pairing(site.id, site.name), sandbox = site.mode == SiteModes.SANDBOX, tasks = emptyList())
        checkFlow.reset() // another site: the server is asked again whether box checks are allowed there
        log("Site: ${site.name}")
        refreshTasks()
    }

    fun cycleScanner() {
        val all = ScannerKind.entries
        setScanner(all[(all.indexOf(_ui.value.scanner) + 1) % all.size])
    }

    /** M5-U05: Settings › Scanning with (Glasses / Phone camera / Handheld). */
    fun setScanner(next: ScannerKind) {
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

    fun toggleAttentionWord() {
        val on = !_ui.value.attentionWord
        prefs.edit().putBoolean(KEY_ATTENTION, on).apply()
        _ui.value = _ui.value.copy(attentionWord = on)
        toast(if (on) "Start what you say with “Field”, like “Field, next”." else "Attention word off: everything said in a work session is heard.")
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
            appendLine("SCMTIPS sign-in: ${u.signedIn?.let { "${it.coreBaseUrl}; approver ${it.approver}; field work ${it.fieldOperator}" } ?: "none"}")
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

    // --- M5-U shell ------------------------------------------------------------------------------

    private fun restoreShell(connectedAtStart: Boolean) {
        fun flag(key: String): Boolean? = if (prefs.contains(key)) prefs.getBoolean(key, false) else null
        val v = ShellView(
            welcomeSeen = FirstRun.initialFlag(flag(KEY_WELCOME), connectedAtStart),
            setupDone = FirstRun.initialFlag(flag(KEY_SETUP), connectedAtStart),
            savedHome = prefs.getString(KEY_HOME, null),
            classic = prefs.getBoolean(KEY_CLASSIC, false),
            reduceMotion = _ui.value.shell.reduceMotion,
        )
        saveShell(v)
        _ui.value = _ui.value.copy(shell = v)
    }

    private fun saveShell(v: ShellView) {
        prefs.edit().putBoolean(KEY_WELCOME, v.welcomeSeen).putBoolean(KEY_SETUP, v.setupDone).putBoolean(KEY_CLASSIC, v.classic)
            .apply { if (v.savedHome == null) remove(KEY_HOME) else putString(KEY_HOME, v.savedHome) }.apply()
    }

    /** Every shell navigation (first run, tabs, pages, role switcher, classic layout); the rules are ShellNav's. */
    fun shell(a: ShellAction) {
        val u = _ui.value
        val next = ShellNav.reduce(u.shell, a, connected = u.signedIn != null || u.pairing != null)
        if (next == u.shell) return
        if (next.welcomeSeen != u.shell.welcomeSeen || next.setupDone != u.shell.setupDone || next.savedHome != u.shell.savedHome ||
            next.classic != u.shell.classic) saveShell(next)
        if (next.classic != u.shell.classic) log("Layout: ${if (next.classic) "classic" else "new"}")
        _ui.value = u.copy(shell = next)
    }

    /** MainActivity.onResume: Android's "Remove animations" (ANIMATOR_DURATION_SCALE == 0). */
    fun setReduceMotion(on: Boolean) {
        if (_ui.value.shell.reduceMotion != on) _ui.value = _ui.value.copy(shell = _ui.value.shell.copy(reduceMotion = on))
    }

    /** Settings › Connections while signed out: the two server addresses the next sign-in uses (checked as on sign-in). */
    fun setServers(coreUrl: String, fieldUrl: String) {
        if (account != null || _ui.value.pairing != null) return toast("Sign out first to change the servers.")
        val (core, coreWhy) = SignInDefaults.check(coreUrl, "SCMTIPS")
        val (field, fieldWhy) = SignInDefaults.check(fieldUrl, "SCMTips Field server")
        if (core == null || field == null) return toast(coreWhy ?: fieldWhy)
        accounts.rememberServers(core, field)
        _ui.value = _ui.value.copy(signIn = _ui.value.signIn.copy(coreUrl = core, fieldUrl = field, error = null))
        toast("Servers saved. Sign in to use them.")
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
        is HttpError -> FieldAccess.noFieldRole(e) ?: when (e.status) {
            401 -> if (account != null) "Your SCMTIPS sign-in expired or the PC restarted. Sign out in Me and sign in again."
            else "The pairing code expired or the PC restarted. Make a new code on the PC and scan it."
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
        stopReview(silent = true)
        stopClaimReview(silent = true)
        stopLaunches()
        loops?.cancel()
        location.stop()
        glasses.disconnect()
        phoneSpeech.destroy()
        continuous.stop()
        tts.shutdown()
    }

    private fun JsonObject.s(k: String): String? = (this[k] as? JsonPrimitive)?.contentOrNull

    companion object {
        /** The sign-in screen after a revoked phone (M5-H06). */
        const val REVOKED_SIGN_IN_AGAIN = "This phone was removed in the SCMTips Field console. Sign in again to add it as a new device."
        private const val KEY_PAIRING = "pairing"
        private const val KEY_SCANNER = "scanner"
        private const val KEY_AUDIO_ONLY = "audio_only"
        private const val KEY_GLASSES_SPEECH = "glasses_speech"
        private const val KEY_VISIT = "visit_id"
        private const val KEY_VISIT_SITE = "visit_site_id"
        private const val KEY_CLIMB_SEQ = "climb_seq"
        private const val KEY_ATTENTION = "attention_word"
        private const val KEY_WELCOME = "shell_welcome_seen"
        private const val KEY_SETUP = "shell_setup_done"
        private const val KEY_HOME = "shell_home"
        private const val KEY_CLASSIC = "shell_classic_layout"

        /** Answers meaning "this core has no POST /v1/auth/app/token" (then the wearable pairing is tried). */
        private val NO_APP_SIGN_IN = setOf(404, 405, 501)
        private const val REVIEW_LISTEN_SESSION_MS = 15_000L
        private const val REVIEW_LISTEN_PHONE_MS = 25_000L
        private const val HEARTBEAT_MS = 5 * 60_000L
        /** How long a look waits for the phone camera app before it gives up. */
        private const val PHONE_PHOTO_MS = 120_000L
    }
}
