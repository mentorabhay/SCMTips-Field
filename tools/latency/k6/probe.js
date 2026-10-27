import http from 'k6/http';
import { check, sleep } from 'k6';

// k6 Latency Benchmark driving POST /v1/diagnostics/probe (Task T1.068 / TC1.157)
// Stages: 10 rps, 50 rps, 100 rps

export const options = {
  scenarios: {
    ten_rps: {
      executor: 'constant-arrival-rate',
      rate: 10,
      timeUnit: '1s',
      duration: '10s',
      preAllocatedVUs: 10,
      maxVUs: 50,
    },
    fifty_rps: {
      executor: 'constant-arrival-rate',
      rate: 50,
      timeUnit: '1s',
      duration: '10s',
      startTime: '10s',
      preAllocatedVUs: 30,
      maxVUs: 100,
    },
    hundred_rps: {
      executor: 'constant-arrival-rate',
      rate: 100,
      timeUnit: '1s',
      duration: '10s',
      startTime: '20s',
      preAllocatedVUs: 50,
      maxVUs: 200,
    },
  },
  thresholds: {
    http_req_duration: ['p(50)<50', 'p(95)<150'], // server duration targets in ms
    http_req_failed: ['rate<0.01'],
  },
};

const BASE_URL = __ENV.FIELD_API_URL || 'http://127.0.0.1:8000';
const TOKEN = __ENV.FIELD_AUTH_TOKEN || 'test-bearer-token';

export default function () {
  const payload = JSON.stringify({
    client_sent_ms: Date.now(),
    device_id: 'DEV-TEST-001',
    is_probe: true,
  });

  const params = {
    headers: {
      'Content-Type': 'application/json',
      'Authorization': `Bearer ${TOKEN}`,
      'traceparent': '00-4bf92f3577b34da6a3ce929d0e0e4736-00f067aa0ba902b7-01',
    },
  };

  const res = http.post(`${BASE_URL}/v1/diagnostics/probe`, payload, params);

  check(res, {
    'status is 200': (r) => r.status === 200,
    'has probe_id': (r) => JSON.parse(r.body).probe_id !== undefined,
  });

  sleep(0.01);
}
