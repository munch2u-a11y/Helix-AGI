/* -------------------------------------------------------------------
   Helix Subconscious Over-Agent — Real-Time 3D WebGL Helix Mascot Character
   Precision 3D Model: Vertical Double-Helix DNA Body, Top Head Loop,
   Dual Antennae, Expressive 3D Face, Metallic Shaders & Mouse Follow.
------------------------------------------------------------------- */

class Helix3DMascot {
    constructor(canvasId) {
        this.canvas = document.getElementById(canvasId);
        if (!this.canvas) return;

        this.scene = new THREE.Scene();
        this.camera = new THREE.PerspectiveCamera(45, 1, 0.1, 1000);
        this.camera.position.set(0, 0, 12);

        this.renderer = new THREE.WebGLRenderer({
            canvas: this.canvas,
            alpha: true,
            antialias: true
        });
        this.renderer.setClearColor(0x000000, 0); // 100% Transparent background
        this.renderer.setSize(200, 240);
        this.renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));

        this.targetMouse = new THREE.Vector2(0, 0);
        this.currentMouse = new THREE.Vector2(0, 0);
        this.time = 0;

        this.moodColors = {
            focused: { primary: 0x00F0FF, secondary: 0x7000FF },
            excited: { primary: 0xFF007A, secondary: 0xFFB800 },
            calm: { primary: 0x00FF99, secondary: 0x00F0FF },
            reflective: { primary: 0xE000FF, secondary: 0x4B0082 }
        };

        this.initLights();
        this.build3DHelixAgentModel();
        this.initMouseEvents();
        this.animate();
    }

    initLights() {
        this.ambientLight = new THREE.AmbientLight(0xffffff, 0.85);
        this.scene.add(this.ambientLight);

        this.primaryLight = new THREE.PointLight(0x00F0FF, 4, 30);
        this.primaryLight.position.set(6, 6, 8);
        this.scene.add(this.primaryLight);

        this.secondaryLight = new THREE.PointLight(0x7000FF, 3, 30);
        this.secondaryLight.position.set(-6, -6, 6);
        this.scene.add(this.secondaryLight);

        const dirLight = new THREE.DirectionalLight(0xffffff, 1.0);
        dirLight.position.set(0, 10, 10);
        this.scene.add(dirLight);
    }

    build3DHelixAgentModel() {
        this.characterGroup = new THREE.Group();
        this.scene.add(this.characterGroup);

        // 1. 3D Vertical Double-Helix DNA Strand Body
        this.helixBodyGroup = new THREE.Group();
        this.characterGroup.add(this.helixBodyGroup);

        const createDnaStrand = (phaseOffset, mainHex) => {
            const points = [];
            const steps = 70;
            const height = 4.8;
            const turns = 1.8;
            const radius = 1.25;

            for (let i = 0; i <= steps; i++) {
                const t = i / steps;
                const y = (t - 0.5) * height - 0.6;
                const angle = t * Math.PI * 2 * turns + phaseOffset;
                const x = Math.cos(angle) * radius;
                const z = Math.sin(angle) * radius;
                points.push(new THREE.Vector3(x, y, z));
            }

            const curve = new THREE.CatmullRomCurve3(points);
            const tubeGeo = new THREE.TubeGeometry(curve, 70, 0.2, 12, false);
            const tubeMat = new THREE.MeshStandardMaterial({
                color: mainHex,
                metalness: 0.9,
                roughness: 0.15,
                emissive: mainHex,
                emissiveIntensity: 0.35
            });

            return new THREE.Mesh(tubeGeo, tubeMat);
        };

        this.strandA = createDnaStrand(0, 0x00F0FF);
        this.strandB = createDnaStrand(Math.PI, 0x7000FF);
        this.helixBodyGroup.add(this.strandA);
        this.helixBodyGroup.add(this.strandB);

        // 3D Base Pair Connecting Rungs
        for (let i = 0; i < 6; i++) {
            const t = (i + 1) / 7;
            const y = (t - 0.5) * 4.0 - 0.6;
            const angle = t * Math.PI * 2 * 1.8;
            const r = 1.15;

            const x1 = Math.cos(angle) * r;
            const z1 = Math.sin(angle) * r;
            const x2 = Math.cos(angle + Math.PI) * r;
            const z2 = Math.sin(angle + Math.PI) * r;

            const p1 = new THREE.Vector3(x1, y, z1);
            const p2 = new THREE.Vector3(x2, y, z2);

            const rungCurve = new THREE.LineCurve3(p1, p2);
            const rungGeo = new THREE.TubeGeometry(rungCurve, 2, 0.065, 8, false);
            const rungMat = new THREE.MeshStandardMaterial({
                color: 0x00F0FF,
                metalness: 0.95,
                emissive: 0x00F0FF,
                emissiveIntensity: 0.45
            });
            this.helixBodyGroup.add(new THREE.Mesh(rungGeo, rungMat));

            // Small glowing sphere on rung ends
            const sphereGeo = new THREE.SphereGeometry(0.1, 12, 12);
            const sphereMat = new THREE.MeshBasicMaterial({ color: 0x00F0FF });
            const s1 = new THREE.Mesh(sphereGeo, sphereMat);
            s1.position.copy(p1);
            const s2 = new THREE.Mesh(sphereGeo, sphereMat);
            s2.position.copy(p2);
            this.helixBodyGroup.add(s1);
            this.helixBodyGroup.add(s2);
        }

        // 2. 3D Character Head (Positioned in Top Loop)
        this.headGroup = new THREE.Group();
        this.headGroup.position.set(0, 1.5, 0);
        this.characterGroup.add(this.headGroup);

        const headGeo = new THREE.SphereGeometry(1.3, 32, 32);
        this.headMat = new THREE.MeshStandardMaterial({
            color: 0x121927,
            metalness: 0.8,
            roughness: 0.2,
            emissive: 0x00F0FF,
            emissiveIntensity: 0.25
        });
        this.headMesh = new THREE.Mesh(headGeo, this.headMat);
        this.headGroup.add(this.headMesh);

        // Inner Glowing Crystal Nucleus
        const coreGeo = new THREE.IcosahedronGeometry(0.55, 1);
        this.coreMat = new THREE.MeshBasicMaterial({ color: 0x00F0FF });
        this.coreMesh = new THREE.Mesh(coreGeo, this.coreMat);
        this.headGroup.add(this.coreMesh);

        // 3D Top Antennae
        const createAntenna = (xOffset) => {
            const group = new THREE.Group();
            const stemGeo = new THREE.CylinderGeometry(0.04, 0.04, 0.7, 8);
            const stemMat = new THREE.MeshStandardMaterial({ color: 0x00F0FF, metalness: 0.9 });
            const stem = new THREE.Mesh(stemGeo, stemMat);
            stem.position.y = 1.5;
            stem.position.x = xOffset;
            stem.rotation.z = -xOffset * 0.4;
            group.add(stem);

            const tipGeo = new THREE.SphereGeometry(0.13, 16, 16);
            this.tipMat = new THREE.MeshBasicMaterial({ color: 0x00F0FF });
            const tip = new THREE.Mesh(tipGeo, this.tipMat);
            tip.position.set(xOffset * 1.3, 1.85, 0);
            group.add(tip);

            return group;
        };

        this.headGroup.add(createAntenna(-0.4));
        this.headGroup.add(createAntenna(0.4));

        // 3. 3D Expressive Face (Glowing Eyes & Cheerful Smile)
        this.eyeGroup = new THREE.Group();
        this.eyeGroup.position.set(0, 0.1, 1.22);
        this.headGroup.add(this.eyeGroup);

        const eyeGeo = new THREE.SphereGeometry(0.18, 16, 16);
        this.eyeMat = new THREE.MeshBasicMaterial({ color: 0xFFFFFF });

        this.eyeLeft = new THREE.Mesh(eyeGeo, this.eyeMat);
        this.eyeLeft.position.set(-0.4, 0, 0);
        this.eyeLeft.scale.set(1, 1.2, 0.4);

        this.eyeRight = new THREE.Mesh(eyeGeo, this.eyeMat);
        this.eyeRight.position.set(0.4, 0, 0);
        this.eyeRight.scale.set(1, 1.2, 0.4);

        this.eyeGroup.add(this.eyeLeft);
        this.eyeGroup.add(this.eyeRight);

        // Smile Curve
        const mouthCurve = new THREE.QuadraticBezierCurve3(
            new THREE.Vector3(-0.25, -0.32, 1.24),
            new THREE.Vector3(0, -0.48, 1.27),
            new THREE.Vector3(0.25, -0.32, 1.24)
        );
        const mouthGeo = new THREE.TubeGeometry(mouthCurve, 16, 0.04, 8, false);
        this.mouthMat = new THREE.MeshBasicMaterial({ color: 0xFFFFFF });
        this.mouthMesh = new THREE.Mesh(mouthGeo, this.mouthMat);
        this.headGroup.add(this.mouthMesh);
    }

    initMouseEvents() {
        window.addEventListener("mousemove", (e) => {
            const x = (e.clientX / window.innerWidth) * 2 - 1;
            const y = -(e.clientY / window.innerHeight) * 2 + 1;
            this.targetMouse.set(x, y);
        });
    }

    setMood(moodName) {
        const mood = this.moodColors[moodName] || this.moodColors.focused;

        this.primaryLight.color.setHex(mood.primary);
        this.secondaryLight.color.setHex(mood.secondary);
        this.strandA.material.color.setHex(mood.primary);
        this.strandA.material.emissive.setHex(mood.primary);
        this.strandB.material.color.setHex(mood.secondary);
        this.strandB.material.emissive.setHex(mood.secondary);
        this.coreMat.color.setHex(mood.primary);
        this.tipMat.color.setHex(mood.primary);
    }

    animate() {
        requestAnimationFrame(() => this.animate());
        this.time += 0.025;

        this.currentMouse.lerp(this.targetMouse, 0.05);

        // 3D Floating Bobbing & Mouse Following
        if (this.characterGroup) {
            this.characterGroup.position.y = Math.sin(this.time) * 0.22;
            this.characterGroup.rotation.y = Math.sin(this.time * 0.5) * 0.12;
            this.characterGroup.rotation.x = this.currentMouse.y * 0.22;
            this.characterGroup.rotation.y += this.currentMouse.x * 0.32;
        }

        // Rotate Double-Helix Body Strands
        if (this.helixBodyGroup) {
            this.helixBodyGroup.rotation.y += 0.015;
        }

        // Pulse Inner Core Crystal
        if (this.coreMesh) {
            this.coreMesh.rotation.x += 0.02;
            this.coreMesh.rotation.y += 0.03;
            const scale = 1 + Math.sin(this.time * 3) * 0.15;
            this.coreMesh.scale.set(scale, scale, scale);
        }

        this.renderer.render(this.scene, this.camera);
    }
}

document.addEventListener("DOMContentLoaded", () => {
    window.helix3DMascot = new Helix3DMascot("helix-3d-canvas");
});
