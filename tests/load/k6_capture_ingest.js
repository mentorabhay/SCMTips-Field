import http from "k6/http";
import { check, sleep } from "k6";

export const options = {
  scenarios: {
    constant_capture_ingest: {
      executor: "constant-arrival-rate",
      rate: 50, // 50 requests per second (TC2.153)
      timeUnit: "1s",
      duration: "10m", // 10 minutes duration
      preAllocatedVUs: 60,
      maxVUs: 120,
    },
  },
  thresholds: {
    http_req_duration: ["p(95)<120"], // p95 at or below 120 ms (TC2.153)
    http_req_failed: ["rate<0.001"],   // 0 5xx server errors
  },
};

const BASE_URL = __ENV.FIELD_API_URL || "http://127.0.0.1:8000";
const DUMMY_CROP_BYTES = "A".repeat(40 * 1024); // 40 KB crop

export default function () {
  const vuId = __VU;
  const iterId = __ITER;
  const isReplay = Math.random() < 0.05;      // 5% replays
  const isDuplicate = Math.random() < 0.02;   // 2% duplicates

  const idempotencyKey = isReplay
    ? `k6-key-replay-${vuId}-${Math.floor(iterId / 2)}`
    : `k6-key-${vuId}-${iterId}-${Date.now()}`;

  const codeValue = isDuplicate
    ? "001234567890123456" // constant code for duplicate trigger
    : `00${vuId}${iterId}${Date.now()}`.padEnd(18, "0").slice(0, 18);

  const metadata = JSON.stringify({
    device_id: `dev-k6-${vuId}`,
    task_id: "task-k6-load-test",
    site_id: "site-tx-austin-wh1",
    user_id: "user-k6-operator",
    shutter_timestamp: Date.now(),
    blur_applied: true,
    code_type: "GS1_128",
    code_value: codeValue,
    readability: 0.95,
    rank_score: 0.88,
  });

  const payload = {
    metadata: metadata,
    crop: http.file(DUMMY_CROP_BYTES, "crop.jpg", "image/jpeg"),
  };

  const params = {
    headers: {
      Authorization: `Bearer mock-token-k6`,
      "Idempotency-Key": idempotencyKey,
    },
    timeout: "5s",
  };

  const res = http.post(`${BASE_URL}/v1/captures`, payload, params);

  if (isDuplicate && !isReplay) {
    check(res, {
      "duplicate returns 409": (r) => r.status === 409 || r.status === 201,
    });
  } else if (isReplay) {
    check(res, {
      "replay returns 201 or 200": (r) => r.status === 200 || r.status === 201,
    });
  } else {
    check(res, {
      "ingest status is 201": (r) => r.status === 201,
      "no 5xx error": (r) => r.status < 500,
    });
  }
}
