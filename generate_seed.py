#!/usr/bin/env python3
"""
Synthetic Seed Dataset Generator for ClaimGuard AI
Generates realistic technical patents for patent infringement analysis.
"""

import json
from pathlib import Path
from typing import Any, Dict, List


class SeedDataGenerator:
    """Generates synthetic patent data for ClaimGuard AI Phase 1."""

    PATENTS_DATA: List[Dict[str, Any]] = [
        {
            "patent_id": "US-2023-001456",
            "title": "Autonomous Vehicle Path Planning Using Quantum-Enhanced Reinforcement Learning",
            "abstract": "A system and method for real-time path optimization in autonomous vehicles using quantum computing acceleration combined with deep reinforcement learning algorithms. The invention provides sub-100ms decision latency for dynamic obstacle avoidance in complex urban environments.",
            "claims": [
                "A method for autonomous path planning comprising: receiving real-time sensor data from LiDAR and camera arrays; encoding the environment state into quantum-compatible representations; applying quantum variational circuits to compute optimal trajectories; executing classical post-processing for real-world implementation constraints.",
                "The system of claim 1, wherein quantum circuits operate on 128-qubit processors with coherence times exceeding 1000 microseconds.",
                "A apparatus for dynamic path optimization further comprising: reinforcement learning agents trained on synthetic urban environments with more than 10 million simulation hours; integration with V2X communication protocols for fleet coordination.",
            ],
            "category": "Autonomous Systems",
        },
        {
            "patent_id": "US-2023-008934",
            "title": "Post-Quantum Cryptographic Signature Scheme Using Lattice-Based Problems",
            "abstract": "A novel cryptographic signature algorithm based on shortest vector problems in high-dimensional lattices, resistant to attacks from both classical and quantum computers. The scheme provides signature sizes under 2KB while maintaining 256-bit equivalent security.",
            "claims": [
                "A cryptographic method comprising: generating random lattice bases in dimension d >= 512; applying Gaussian elimination with noise perturbation for key generation; implementing Fiat-Shamir transformation for interactive-to-non-interactive conversion.",
                "The signature scheme of claim 1 achieving deterministic random bit generation through rejection sampling with computational cost O(d^2 log d).",
                "A digital certificate infrastructure utilizing lattice signatures for blockchain consensus mechanisms with transaction throughput of 100k+ transactions per second.",
            ],
            "category": "Cryptography",
        },
        {
            "patent_id": "US-2023-015678",
            "title": "Smart Grid Demand Response System Using Federated Learning and Edge Computing",
            "abstract": "An intelligent power distribution system that predicts and manages electricity demand across distributed grids using federated machine learning at the edge, without centralizing sensitive consumer data. Achieves 15% peak load reduction while maintaining grid stability.",
            "claims": [
                "A federated learning framework for smart grids comprising: local neural networks deployed on edge devices (smart meters and substations); secure aggregation of model updates using homomorphic encryption; global model synchronization via byzantine-robust averaging.",
                "The system of claim 1 further including real-time pricing signals generated from decentralized prediction models with 94% accuracy in demand forecasting.",
                "An apparatus for grid stability control implementing decentralized voltage regulation using only local measurements within 500-millisecond control loops.",
            ],
            "category": "Smart Grid",
        },
        {
            "patent_id": "US-2023-022401",
            "title": "Real-Time 3D Object Detection Using Sparse Convolutional Neural Networks and Event Cameras",
            "abstract": "A computer vision system combining event-based cameras with sparse 3D convolutions for ultra-low-latency object detection in autonomous robotics. Processes 1000+ frames per second with sub-10ms latency while consuming 90% less power than traditional approaches.",
            "claims": [
                "A method for object detection in dynamic scenes comprising: capturing asynchronous pixel-level events from event cameras; encoding events as sparse 3D tensors; applying minkowski convolutional neural networks for feature extraction and bounding box regression.",
                "The vision system of claim 1 achieving real-time performance on mobile edge devices with computational budget under 2 TFLOPS.",
                "An integrated hardware-software pipeline using FPGA acceleration for event encoding and sparse tensor operations with deterministic latency bounds.",
            ],
            "category": "Computer Vision",
        },
        {
            "patent_id": "US-2023-031847",
            "title": "Hierarchical Vector Database with Approximate Nearest Neighbor Search and Adaptive Indexing",
            "abstract": "A scalable database system optimized for similarity search on high-dimensional vector embeddings with dynamic adaptive indexing based on query patterns. Supports ANNS queries with 99th percentile latency under 50ms on billion-scale embeddings.",
            "claims": [
                "A vector database architecture comprising: hierarchical clustering of embeddings using balanced k-d trees; learned index structures that adapt to query distributions; approximate nearest neighbor algorithms using product quantization.",
                "The database system of claim 1 implementing sharding strategies across distributed nodes with automatic rebalancing based on access patterns.",
                "A method for index optimization using online learning algorithms that predict query selectivity and dynamically adjust index granularity with negligible overhead.",
            ],
            "category": "Vector Databases",
        },
    ]

    @classmethod
    def generate(cls, output_path: str = "data/seed_patents.json") -> str:
        """
        Generate seed patent data and save to JSON file.

        Args:
            output_path: Path where seed data JSON file will be written.

        Returns:
            Path to the generated file.
        """
        output_file = Path(output_path)
        output_file.parent.mkdir(parents=True, exist_ok=True)

        seed_data = {
            "version": "1.0.0",
            "generated_for": "ClaimGuard AI Phase 1",
            "total_patents": len(cls.PATENTS_DATA),
            "patents": cls.PATENTS_DATA,
        }

        with open(output_file, "w", encoding="utf-8") as f:
            json.dump(seed_data, f, indent=2, ensure_ascii=False)

        return str(output_file)


def main() -> None:
    """Main entry point for seed data generation."""
    output_path = SeedDataGenerator.generate()
    print(f"✓ Seed data generated successfully at: {output_path}")
    print(f"✓ Total patents: {len(SeedDataGenerator.PATENTS_DATA)}")

    with open(output_path, "r", encoding="utf-8") as f:
        data = json.load(f)
        print(f"✓ File size: {len(json.dumps(data).encode('utf-8'))} bytes")
        print("\nPatents generated:")
        for patent in data["patents"]:
            print(f"  - {patent['patent_id']}: {patent['title'][:60]}...")


if __name__ == "__main__":
    main()
