package com.scmtips.field.feature.exploded

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test
import java.nio.file.Files
import kotlin.random.Random

/** Exploded-view transforms (FR4.055). View-model only: no renderer exists, so TC4.147 (fps) is not covered. */
class ExplodedViewModelTest {

    private val psu = ExplodedBomItem(3, "PSU-1", "PSU", 1, true, listOf("psu_node"), Vector3(0f, 0.12f, 0f), assembledPosition = Vector3(0.1f, 0.2f, 0.3f))
    private val rru = ExplodedBomItem(1, "RRU-1", "RRU body", 1, true, listOf("rru_a", "rru_b"), Vector3(0.05f, 0f, -0.4f))

    private fun close(a: Vector3, b: Vector3) = kotlin.math.abs(a.x - b.x) < 1e-6 && kotlin.math.abs(a.y - b.y) < 1e-6 && kotlin.math.abs(a.z - b.z) < 1e-6

    @Test
    fun tc4_025_atZeroPartsAreAtAssembledPositions_fr4_055() {
        assertEquals(psu.assembledPosition, psu.computePosition(0f))
        assertEquals(rru.assembledPosition, rru.computePosition(0f))
    }

    @Test
    fun tc4_026_atOneOffsetEqualsExplodeVector_fr4_055() {
        assertTrue(close(Vector3(0.1f, 0.32f, 0.3f), psu.computePosition(1f)))
    }

    @Test
    fun tc4_027_overshootClampedToOne_fr4_055() {
        assertEquals(psu.computePosition(1f), psu.computePosition(1.4f))
        assertEquals(psu.computePosition(0f), psu.computePosition(-0.5f))
    }

    /** Seeded sweep: position is linear in t within 1e-6 m. */
    @Test
    fun fr4_055_positionLinearInT() {
        val random = Random(409)
        repeat(1000) {
            val v = Vector3(random.nextFloat() - 0.5f, random.nextFloat() - 0.5f, random.nextFloat() - 0.5f)
            val p0 = Vector3(random.nextFloat(), random.nextFloat(), random.nextFloat())
            val item = ExplodedBomItem(null, "P", "p", 1, false, listOf("n"), v, assembledPosition = p0)
            val t = random.nextFloat()
            assertTrue(close(Vector3(p0.x + t * v.x, p0.y + t * v.y, p0.z + t * v.z), item.computePosition(t)))
        }
    }

    @Test
    fun fr4_055_sliderDrivesEveryNodeTransform() {
        val dir = Files.createTempDirectory("pack").toFile()
        java.io.File(dir, "rru.glb").writeBytes(byteArrayOf(0x67, 0x6C, 0x54, 0x46))
        val vm = ExplodedViewModel("M1", "RRU", "1.0.0", dir)
        vm.loadModelFromSitePack("rru.glb", listOf(psu, rru))
        assertTrue(vm.state.isLoaded)
        vm.setExplodeT(0.5f)
        val tf = vm.getNodeTransforms()
        assertEquals(setOf("psu_node", "rru_a", "rru_b"), tf.keys)
        assertTrue(close(Vector3(0.025f, 0f, -0.2f), tf.getValue("rru_b")))
        assertNull(vm.state.currentFps)
    }

    @Test
    fun missingModelFileIsNotReportedAsLoaded() {
        val vm = ExplodedViewModel("M1", "RRU", "1.0.0", Files.createTempDirectory("pack").toFile())
        vm.loadModelFromSitePack("absent.glb", listOf(psu))
        assertFalse(vm.state.isLoaded)
        assertNotNull(vm.state.errorMessage)
        assertTrue(vm.getNodeTransforms().isEmpty())
        val noDir = ExplodedViewModel("M1", "RRU", "1.0.0", null)
        noDir.loadModelFromSitePack("x.glb", listOf(psu))
        assertFalse(noDir.state.isLoaded)
    }
}
