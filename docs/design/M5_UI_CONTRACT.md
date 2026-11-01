# M5-U UI contract: the shell seam (A-07)

Owner of this file: builder A (feat/m5-ui-shell, M5-U01 / M5-U05). It fixes the names builder B's screens
(feat/m5-ui-screens: `ui/firstrun/*`, `ui/homes/*`) and builder C's task screens (feat/m5-ui-tasks) plug into.
Nothing here is proven on the owner's phone or glasses; every M5-U row stays partial until it is.

All paths below are under `apps/field-android/app/src/main/kotlin/com/scmtips/field/app/`.

## 1. Where the new screens plug in

| Seam | File (builder A) | Signature | What the integrator changes |
|---|---|---|---|
| First run | `ui/shell/FirstRunContent.kt` | `@Composable fun FirstRunContent(step: FirstRunStep, ui: AppUi, a: Actions)` | one `when` branch per step: replace the `Interim…` call with B's screen |
| Role homes | `ui/shell/HomeContent.kt` | `@Composable fun HomeContent(home: Home, ui: AppUi, a: Actions, canAct: Boolean)` | one `when` branch per home: replace the `Interim…Home` call with B's home |

`AppRoot` decides *which* step or home is drawn (`FirstRun.step`, `HomeMemory.current`); B's screens never
navigate by themselves, they only call the callbacks they are given. B's files must not import `Actions`, `AppUi`
or `FieldController`: they take explicit parameters and lambdas; B's pure mappers (AppUi → small models) may
read `AppUi`.

## 2. Pure types B may use (package `com.scmtips.field.app.shell`, JVM-tested)

- `Home { WAREHOUSE, TOWER, APPROVALS, SCAN }` with `label`, `menuLabel`; `Capabilities(fieldOperator, approver, towerTasks)`;
  `HomeChoice(home, canAct)` (`badge` = "can act" / "view only"); `HomeRules.choices / defaultHome / canAct / viewOnlyBanner /
  towerTasks / warehouseTasks`.
- `FirstRunStep { WELCOME, SIGN_IN, FORGOT, PERMISSIONS, GLASSES, SITE }`, `PermissionStep { CAMERA, MICROPHONE, NEARBY,
  NOTIFICATIONS }` (title, why), `Tab`, `ShellPage`, `ShellAction`, `AccountPages.reset / signup`, `StatusPill`, `ShellText`.

## 3. Screens builder B provides (names and parameters the integrator expects)

First run (`ui/firstrun/`), each full screen, own Back where the prototype has one:

```kotlin
WelcomeScreen(reduceMotion: Boolean, onGetStarted: () -> Unit, onJudgeDetails: () -> Unit)
SignInScreen(state: SignInView, onSignIn: (SignInMethod, coreUrl: String, fieldUrl: String) -> Unit,
             onForgot: () -> Unit, onCreateAccount: (coreUrl: String) -> Unit, onPcCode: () -> Unit, onBack: () -> Unit)
ForgotScreen(email: String, onOpenReset: () -> Unit, onCreateAccount: () -> Unit, onBack: () -> Unit)
PermissionsScreen(reduceMotion: Boolean, onAllow: (PermissionStep) -> Unit, onDone: () -> Unit)   // "Not now" skips a step, never asks
GlassesSetupScreen(advice: GlassesAdvice, reduceMotion: Boolean, onSetUp: () -> Unit, onTestPhoto: () -> Unit,
                   onSkip: () -> Unit, onContinue: () -> Unit)
SitePickScreen(personName: String, sites: List<SiteRef>, currentSiteId: String?, homes: List<HomeChoice>, selected: Home,
               onSite: (siteId: String) -> Unit, onHome: (Home) -> Unit, onContinue: () -> Unit)
```

Homes (`ui/homes/`): `WarehouseHome`, `TowerHome`, `ApprovalsHome`, `ScanHome`, each `(model, canAct: Boolean, callbacks…)`.
A home draws only the content **below** the shell's header: the shell already draws the night header ("Working as
<Home> ▾" switcher, status pill, greeting with name and site), the connection card and the view-only banner, and the
tab bar under it. A home must scroll by itself, show a designed empty state when its model is empty, never show
sample or invented data as real, and hide or disable its act buttons when `canAct` is false.

## 4. How the integrator binds the callbacks (all exist in `ui/AppRoot.kt` `Actions`)

| Callback | Bind to |
|---|---|
| onGetStarted, onJudgeDetails | `a.shell(ShellAction.Welcomed)` |
| onForgot / onBack | `a.shell(ShellAction.Go(FirstRunStep.FORGOT))` / `a.shell(ShellAction.Back)` |
| onSignIn | `a.signIn(method, core, field)` (the shell moves on when signed in) |
| onCreateAccount(core) | `a.openUrl(AccountPages.signup(core, BuildConfig.DEFAULT_CORE_URL))` |
| onOpenReset | `a.openUrl(AccountPages.reset(ui.signIn.coreUrl, BuildConfig.DEFAULT_CORE_URL))` |
| onPcCode | `a.scanPairingCode()` |
| onAllow(step) | `a.requestPermission(step)`; onDone → `a.shell(ShellAction.Go(FirstRunStep.GLASSES))` |
| onSetUp / onTestPhoto | `a.glassesSetUp()` / `a.testCamera()` (the result is `ui.probe`, drawn by `CameraTestCard`) |
| onSkip / onContinue (glasses) | `a.shell(ShellAction.Go(FirstRunStep.SITE))` |
| onSite / onHome / onContinue (site) | `a.chooseSite(id)` / `a.shell(ShellAction.PickHome(home, who))` / `a.shell(ShellAction.FinishSetup)` |
| homes | `a.startWork`, `a.openTask(id)`, `a.openStarter(type)`, `a.startCase(case)`, `a.startSandbox(start, bin)`, `a.refresh`, `a.startReview`, `a.startClaims`, `a.check(CheckAction.START)`, `a.look` |
| any screen → a tab / page | `a.shell(ShellAction.SelectTab(tab))` / `a.shell(ShellAction.Open(page))` |

## 5. Theme and motion (builder A, `ui/theme/`, `ui/Components.kt`)

- Colours (`theme/Color.kt`): `Ink #15171C`, `Muted #5B6170`, `Ground #F5F6F8`, `Surface #FFFFFF`, `Border #E4E7EC`,
  `Night #17181C`, `NightTask #0F1013` (task and camera screens), `Good #157A3C`, `Warning #A15C07`, `Danger #B3261E`,
  `AccentInk #5B21B6`, `BrandStart #6D28D9`, `BrandEnd #C2410C`, `BrandGradient` (a `Brush`, only for the one main button
  per screen and the Scan tab). The M2 names (`Primary`, `Background`, `CardBg`, `Line`, …) stay as aliases of these.
- Shapes and sizes: `CardShape` 16 dp, `ButtonShape` 14 dp, `MinTouch` 48 dp; `GradientButton(text, onClick, modifier,
  enabled, height)` is the one main button; `PrimaryButton` / `SecondaryButton` keep their parameters.
- Remove animations: `LocalReduceMotion` (`theme/Motion.kt`, a `staticCompositionLocalOf<Boolean>`) is provided by
  `AppRoot` from `ui.shell.reduceMotion`, which follows `Settings.Global.ANIMATOR_DURATION_SCALE == 0` (read in
  `MainActivity.onResume`). Every hint animation (builder C's `ui/kit/HintAnimations.kt`, B's welcome and glasses
  art) must draw one still frame when it is true.

## 6. Navigation rules (pure, `shell/ShellNav.kt`, tested)

First run shows only when not signed in and not paired (Welcome until "welcome seen", then Sign in), and after a
new sign-in until Site and role's Continue (`setupDone`, remembered; an install that was already connected before
the redesign skips it). Home: the one chosen in the switcher by this account (remembered), else operator →
Warehouse, approver only → Approvals, else Scan product. Task screens (job, check, decisions, claims, evidence)
are drawn full screen over the shell with no tab bar, exactly as before. Settings › Diagnostics › "Classic layout"
(default off) brings back the old Connect / Today · Scan · Me screens unchanged.
