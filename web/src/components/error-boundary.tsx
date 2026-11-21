import { Component, type ReactNode } from "react"

import { ErrorState } from "@/components/common"

/** Keeps the shell (sidebar, search) alive when a single page throws while rendering. */
export class ErrorBoundary extends Component<{ children: ReactNode; resetKey: string }, { error: unknown }> {
  state = { error: null as unknown }

  static getDerivedStateFromError(error: unknown) {
    return { error }
  }

  componentDidUpdate(prev: { resetKey: string }) {
    if (prev.resetKey !== this.props.resetKey && this.state.error) this.setState({ error: null })
  }

  render() {
    return this.state.error ? <ErrorState error={this.state.error} /> : this.props.children
  }
}
