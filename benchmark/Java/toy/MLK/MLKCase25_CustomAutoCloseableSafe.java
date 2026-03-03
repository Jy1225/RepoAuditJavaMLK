class MLKCase25_CustomAutoCloseableSafe {
    static class LocalRes implements AutoCloseable {
        @Override
        public void close() {
            // no-op
        }
    }

    public void run() throws Exception {
        LocalRes res = new LocalRes();
        res.close();
    }
}
