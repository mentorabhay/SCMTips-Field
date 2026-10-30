package com.scmtips.field.core.outbox.api

import okhttp3.MultipartBody
import okhttp3.OkHttpClient
import okhttp3.RequestBody
import okhttp3.ResponseBody
import retrofit2.Response
import retrofit2.Retrofit
import retrofit2.http.Body
import retrofit2.http.GET
import retrofit2.http.Header
import retrofit2.http.Multipart
import retrofit2.http.POST
import retrofit2.http.Part
import retrofit2.http.Path
import java.util.concurrent.TimeUnit
import okhttp3.MediaType.Companion.toMediaTypeOrNull
import okhttp3.RequestBody.Companion.toRequestBody

interface FieldApiService {

    @POST("/v1/auth/exchange")
    suspend fun exchangeToken(
        @Body request: AuthExchangeRequest
    ): Response<AuthExchangeResponse>

    @GET("/v1/devices/{id}/config")
    suspend fun getDeviceConfig(
        @Path("id") deviceId: String
    ): Response<DeviceConfigResponse>

    @POST("/v1/devices")
    suspend fun registerDevice(
        @Body request: DeviceRegisterRequest
    ): Response<DeviceRegisterResponse>

    @POST("/v1/consents")
    suspend fun recordConsent(
        @Body request: ConsentRecordRequest
    ): Response<ResponseBody>

    @Multipart
    @POST("/v1/captures")
    suspend fun uploadCapture(
        @Part crop: MultipartBody.Part,
        @Part("metadata") metadata: RequestBody
    ): Response<CaptureUploadResponse>

    @GET("/v1/health")
    suspend fun getHealth(): Response<ResponseBody>
}

// Data Transfer Objects matching openapi.yaml
data class AuthExchangeRequest(
    val core_device_token: String,
    val device_id: String,
    val site_id: String? = null
)

data class AuthExchangeResponse(
    val field_jwt: String,
    val expires_in_seconds: Long,
    val tenant_id: String,
    val device_id: String,
    val permissions: List<String>
)

data class DeviceConfigResponse(
    val device_id: String,
    val tenant_id: String,
    val site_id: String?,
    val settings: Map<String, String>
)

data class DeviceRegisterRequest(
    val kind: String,
    val model: String,
    val app_version: String,
    val paired_with: String? = null
)

data class DeviceRegisterResponse(
    val id: String,
    val status: String
)

data class ConsentRecordRequest(
    val user_id: String,
    val device_id: String,
    val site_id: String,
    val consent_type: String = "site_and_bystander_privacy",
    val granted: Boolean = true
)

data class CaptureUploadResponse(
    val capture_id: String,
    val status: String,
    val readability: Double,
    val code_value: String?
)

/**
 * Factory creating configured OkHttpClient with required interceptors.
 */
object FieldApiClientFactory {
    fun createHttpClient(
        tokenProvider: TokenProvider? = null,
        logger: ((String) -> Unit)? = null
    ): OkHttpClient {
        return OkHttpClient.Builder()
            .addInterceptor(HeaderInterceptor(tokenProvider))
            .addInterceptor(RedactingLoggingInterceptor(logger ?: { println(it) }))
            .connectTimeout(10, TimeUnit.SECONDS)
            .readTimeout(15, TimeUnit.SECONDS)
            .writeTimeout(15, TimeUnit.SECONDS)
            .build()
    }
}

/**
 * Client wrapper for network interactions.
 */
class FieldApiClient(
    val baseUrl: String = "https://api.field.scmtips.internal",
    val httpClient: OkHttpClient = FieldApiClientFactory.createHttpClient()
) {
    suspend fun postCaptureSync(
        idempotencyKey: String,
        metadataJson: String,
        cropBytes: ByteArray?
    ): Pair<Int, String?> {
        val requestBody = okhttp3.MultipartBody.Builder()
            .setType(MultipartBody.FORM)
            .addFormDataPart(
                "metadata",
                null,
                metadataJson.toByteArray().toRequestBody("application/json".toMediaTypeOrNull())
            )

        if (cropBytes != null) {
            val imagePart = cropBytes.toRequestBody("image/jpeg".toMediaTypeOrNull())
            requestBody.addFormDataPart("crop", "$idempotencyKey.jpg", imagePart)
        }

        val request = okhttp3.Request.Builder()
            .url("$baseUrl/v1/captures")
            .header("Idempotency-Key", idempotencyKey)
            .post(requestBody.build())
            .build()

        return try {
            httpClient.newCall(request).execute().use { response ->
                Pair(response.code, response.body?.string())
            }
        } catch (e: Exception) {
            Pair(0, e.message)
        }
    }
}
