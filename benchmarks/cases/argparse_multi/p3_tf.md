In `tf.py`, add an optional `epilog_formatter` argument (default None) to
`ArgumentParser.__init__`. When set to a callable, it is called with the epilog
string before it is added to the help output. When None, behavior is unchanged.
Implement minimally. Show the unified diff.
