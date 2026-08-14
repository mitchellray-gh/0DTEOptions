import React from 'react';

/**
 * Catches render/runtime errors in a page so one broken tab can't blank the
 * entire single-page app. Shows a friendly message + a reset button instead.
 */
export default class ErrorBoundary extends React.Component {
  constructor(props) {
    super(props);
    this.state = { error: null };
  }

  static getDerivedStateFromError(error) {
    return { error };
  }

  componentDidCatch(error, info) {
    // eslint-disable-next-line no-console
    console.error('Page crashed:', error, info);
  }

  componentDidUpdate(prevProps) {
    // Reset the error when navigating to a different route.
    if (prevProps.routeKey !== this.props.routeKey && this.state.error) {
      this.setState({ error: null });
    }
  }

  render() {
    if (this.state.error) {
      return (
        <div className="rh-page">
          <div className="rh-card" style={{ marginTop: 20 }}>
            <h4>Something went wrong on this page</h4>
            <p className="rh-lead" style={{ marginTop: 6 }}>
              {String(this.state.error?.message || this.state.error)}
            </p>
            <button
              className="rh-btn block"
              style={{ marginTop: 12 }}
              onClick={() => this.setState({ error: null })}
            >
              Reload this page
            </button>
          </div>
        </div>
      );
    }
    return this.props.children;
  }
}
