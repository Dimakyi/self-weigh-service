# Kafka Broker Outage Recovery Test

**Date:** 2026-11-09  
**Result:** Passed (manual Docker Compose integration smoke test)

## Objective

Verify that a weigh transaction can be accepted while the Kafka broker is unavailable, that its event remains in the transactional outbox, and that the running worker delivers the event after the broker becomes available again.

## Environment

- Docker Compose services: API, PostgreSQL, Redpanda and outbox worker
- Kafka topic: `selfweigh.events`
- Test airline: `ZZ` (`Worker Test Airline`)
- API and worker were already running before the broker was stopped.

## Procedure and observed results

1. **Stop the broker.**

   ```powershell
   docker compose stop redpanda
   ```

   Redpanda stopped while the API, database and worker remained running.

2. **Create a weigh transaction while the broker is unavailable.**

   The API accepted a `POST /weigh` request authenticated with the kiosk key:

   - Transaction ID: `3`
   - Airline code: `ZZ`
   - Flight number: `TEST-OFF1`
   - Weight: `22.0 kg`
   - Excess weight: `2 kg`
   - Fee: `3000` cents (R30.00)
   - Status: `AWAITING_PAYMENT`

   This confirmed that the API could commit the transaction while Kafka was offline.

3. **Observe the worker during the outage.**

   ```powershell
   docker compose logs worker --tail 40
   ```

   The worker logged Kafka connection and DNS resolution failures for `redpanda:9092`. The worker process remained running; it was not manually restarted for the recovery check.

4. **Restart the broker and wait for health.**

   ```powershell
   docker compose start redpanda
   Start-Sleep -Seconds 15
   docker compose ps
   ```

   Redpanda returned to `Up (healthy)`. The API, PostgreSQL and worker containers were also running.

5. **Verify delivery from the Kafka topic.**

   ```powershell
   docker compose exec redpanda rpk topic consume selfweigh.events -o 2 -n 1
   ```

   The consumer returned the event at partition `0`, offset `2`:

   - Event type: `TRANSACTION_WEIGHED`
   - Event ID / message key: `50f68cef-ac30-4edb-bbc2-08a590bdbad9`
   - Transaction ID: `3`
   - Flight number: `TEST-OFF1`
   - Weight: `22.0 kg`
   - Fee: `3000` cents
   - Status: `AWAITING_PAYMENT`

## Conclusion

**Passed.** The API accepted and persisted a weigh transaction while Redpanda was unavailable. After Redpanda recovered, the existing worker delivered the corresponding outbox event to `selfweigh.events` without a manual worker restart.

This is evidence of successful recovery in this manual test scenario. It does not establish exactly-once delivery or prove that duplicate delivery cannot occur. The outbox delivery model is at-least-once; downstream consumers must deduplicate using the event ID.

## Scope and limitations

- This was a manual integration smoke test, not an automated test in the pytest suite.
- The test verified recovery and delivery of this event; it did not measure recovery time or inspect every outbox retry field.
- Duplicate-delivery handling and dead-letter recovery were not tested by this scenario.
- The test used the project's local Docker Compose environment and simulated weigh input; it did not exercise physical scale hardware or a live payment provider.
