import java.io.FileInputStream;
import java.io.InputStream;

class MLKCase35_SwitchBranchAcquireHelperCloseSafe {
    private void closeResource(InputStream in) throws Exception {
        in.close();
    }

    public void run(String path, int mode) throws Exception {
        switch (mode) {
            case 0:
                InputStream in = new FileInputStream(path);
                closeResource(in);
                break;
            default:
                break;
        }
    }
}
