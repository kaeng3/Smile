# Scanner source

The scanner runtime was copied from the validated `jusmo-scanner` branch
`feature/event-location-kis-fixes` at commit `ed81fd2`.

This embedded copy keeps the scanner calculations and KIS provider together
with their regression tests. The standalone CLI, backtest, and share-export
entry points are intentionally excluded because the Smile site uses its own
daily runner.
