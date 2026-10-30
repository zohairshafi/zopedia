import Foundation

public struct TradingService: Sendable {
    private let client: APIClient

    public init(client: APIClient) {
        self.client = client
    }

    public func pendingApprovals() async throws -> PendingApprovalsResponse {
        try await client.get("api/trading/pending-approvals")
    }

    public func approve(id: String) async throws -> TradeDecisionResponse {
        try await client.post("api/trading/pending-approvals/\(id)/approve")
    }

    public func reject(id: String) async throws -> TradeDecisionResponse {
        try await client.post("api/trading/pending-approvals/\(id)/reject")
    }
}
