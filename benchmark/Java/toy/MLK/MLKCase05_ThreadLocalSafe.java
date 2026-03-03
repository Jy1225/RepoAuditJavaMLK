class MLKCase05_ThreadLocalSafe {
    private final ThreadLocal<String> ctx = new ThreadLocal<>();

    public void run(String id) {
        ctx.set(id);
        ctx.remove();
    }
}
