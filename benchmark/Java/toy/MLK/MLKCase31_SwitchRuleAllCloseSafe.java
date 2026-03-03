import java.io.FileInputStream;
import java.io.InputStream;

class MLKCase31_SwitchRuleAllCloseSafe {
    public void run(String path, int mode) throws Exception {
        InputStream in = new FileInputStream(path);
        switch (mode) {
            case 0 -> in.close();
            case 1, 2 -> {
                in.close();
            }
            default -> in.close();
        }
    }
}
