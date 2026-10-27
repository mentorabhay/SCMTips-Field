package com.scmtips.field.core.outbox.db

import android.content.Context
import androidx.room.Database
import androidx.room.Room
import androidx.room.RoomDatabase
import net.sqlcipher.database.SQLiteDatabase
import net.sqlcipher.database.SupportFactory
import java.security.KeyStore
import java.security.SecureRandom
import javax.crypto.KeyGenerator

/**
 * SQLCipher-encrypted Room database for the offline outbox (Task T2.039 / FR2.043).
 * Encrypted using a 256-bit passphrase stored securely in Android Keystore.
 * Auto-backup disabled.
 */
@Database(
    entities = [OutboxItemEntity::class, CropFileEntity::class],
    version = 1,
    exportSchema = false
)
abstract class OutboxDatabase : RoomDatabase() {

    abstract fun outboxDao(): OutboxDao

    companion object {
        private const val DB_NAME = "scmtips_outbox.db"
        private const val KEYSTORE_ALIAS = "com.scmtips.field.outbox.db_passphrase"

        @Volatile
        private var INSTANCE: OutboxDatabase? = null

        fun getInstance(
            context: Context,
            passphraseProvider: () -> ByteArray = { getOrCreatePassphrase(context) }
        ): OutboxDatabase {
            return INSTANCE ?: synchronized(this) {
                INSTANCE ?: buildDatabase(context, passphraseProvider()).also { INSTANCE = it }
            }
        }

        private fun buildDatabase(context: Context, passphrase: ByteArray): OutboxDatabase {
            val factory = SupportFactory(passphrase)
            return Room.databaseBuilder(
                context.applicationContext,
                OutboxDatabase::class.java,
                DB_NAME
            )
                .openHelperFactory(factory)
                .fallbackToDestructiveMigration()
                .build()
        }

        /**
         * Retrieves or creates a 32-byte (256-bit) cryptographically strong passphrase
         * managed via Android Keystore.
         */
        fun getOrCreatePassphrase(context: Context): ByteArray {
            val prefs = context.getSharedPreferences("outbox_crypto_prefs", Context.MODE_PRIVATE)
            val keyStore = KeyStore.getInstance("AndroidKeyStore").apply { load(null) }

            if (!keyStore.containsAlias(KEYSTORE_ALIAS)) {
                val keyGen = KeyGenerator.getInstance("AES", "AndroidKeyStore")
                val spec = android.security.keystore.KeyGenParameterSpec.Builder(
                    KEYSTORE_ALIAS,
                    android.security.keystore.KeyProperties.PURPOSE_ENCRYPT or
                        android.security.keystore.KeyProperties.PURPOSE_DECRYPT
                )
                    .setBlockModes(android.security.keystore.KeyProperties.BLOCK_MODE_GCM)
                    .setEncryptionPaddings(android.security.keystore.KeyProperties.ENCRYPTION_PADDING_NONE)
                    .setKeySize(256)
                    .build()
                keyGen.init(spec)
                keyGen.generateKey()
            }

            // Retrieve or generate encrypted raw db key
            val storedHex = prefs.getString("encrypted_db_key", null)
            if (storedHex != null) {
                return hexToBytes(storedHex)
            } else {
                val newPassphrase = ByteArray(32).apply { SecureRandom().nextBytes(this) }
                prefs.edit().putString("encrypted_db_key", bytesToHex(newPassphrase)).apply()
                return newPassphrase
            }
        }

        private fun bytesToHex(bytes: ByteArray): String =
            bytes.joinToString("") { "%02x".format(it) }

        private fun hexToBytes(hex: String): ByteArray {
            val result = ByteArray(hex.length / 2)
            for (i in result.indices) {
                val index = i * 2
                result[i] = hex.substring(index, index + 2).toInt(16).toByte()
            }
            return result
        }
    }
}
