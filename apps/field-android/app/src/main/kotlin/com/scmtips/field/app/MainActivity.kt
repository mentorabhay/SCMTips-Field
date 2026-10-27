package com.scmtips.field.app

import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import com.scmtips.field.app.navigation.FieldNavGraph
import com.scmtips.field.app.ui.theme.SCMTipsFieldTheme

class MainActivity : ComponentActivity() {
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        
        val app = application as? FieldApplication
        check(app?.isEncryptedOutboxReady == true) {
            "CRITICAL: Encrypted outbox must be opened before UI initialization"
        }

        setContent {
            SCMTipsFieldTheme {
                FieldNavGraph()
            }
        }
    }
}
